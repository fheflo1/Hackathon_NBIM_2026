"""Durable upload queue. The existing, audited LangGraph owns each vote decision."""

import hashlib
import json
import logging
import math
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from .. import triage as triage_lib
from ..local_model import model_identity
from ..operations import provider_error
from ..policy import injection_signals, load_policy, retrieve
from ..store import AuditStore, load_events, now
from ..workflow import pipeline_fingerprint, process_records
from .ingestion import MAX_BYTES, read_agenda

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "needs_attention", "failed"}
LIGHT_VERSION = "light-check-v6"  # bump when prompts change: re-uploads re-run
NBIM_VOTING_URL = "https://www.nbim.no/en/responsible-investment/voting/our-voting-records/"


def stamp(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class AgendaService:
    def __init__(
        self,
        settings,
        processor=process_records,
        reader=read_agenda,
        identity=None,
        triage=None,
        light_checker=None,
        note_writer=None,
    ):
        self.settings, self.processor, self.reader = settings, processor, reader
        # Triage model (LR on agenda structure + NBIM's earlier votes). None = load lazily from
        # settings.triage_model_path; False = off. Without a model every item goes to the agent.
        self._triage = triage
        self._triage_sha = None
        self.light_checker = light_checker or self._light_check
        self.note_writer = note_writer or self._note
        self.identity = identity or (
            lambda: (
                model_identity(
                    replace(settings, timeout_seconds=3),
                    {settings.model, settings.reviewer_model or settings.model},
                )
                if settings.provider == "ollama"
                else {}
            )
        )
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agenda")
        AuditStore(settings.database_path).close()
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS web_jobs (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                status TEXT NOT NULL, payload_json TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS web_fingerprint ON web_jobs(fingerprint)")
            db.execute("""CREATE TABLE IF NOT EXISTS web_job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, event TEXT NOT NULL, payload_json TEXT NOT NULL)""")
            # A restarted server does not claim that an interrupted job finished.
            rows = db.execute(
                "SELECT id,payload_json FROM web_jobs WHERE status NOT IN ('completed','needs_attention','failed')"
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                payload.update(
                    error="Kjøringen ble avbrutt. Last opp filen på nytt; ferdige saker gjenbrukes.",
                    stage="interrupted",
                )
                db.execute(
                    "UPDATE web_jobs SET status='failed',payload_json=?,updated_at=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), now(), row["id"]),
                )

                db.execute(
                    "INSERT INTO web_job_events(job_id,timestamp,event,payload_json) VALUES(?,?,?,?)",
                    (row["id"], now(), "interrupted", json.dumps({"status": "failed"})),
                )

    def connection(self):
        class Connection:
            def __enter__(inner):
                inner.db = sqlite3.connect(self.settings.database_path, timeout=30)
                inner.db.row_factory = sqlite3.Row
                return inner.db

            def __exit__(inner, typ, value, tb):
                if typ is None:
                    inner.db.commit()
                else:
                    inner.db.rollback()
                inner.db.close()

        return Connection()

    def close(self):
        self.stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _read(self, row):
        if row is None:
            raise KeyError("Sakslisten finnes ikke.")
        return dict(
            json.loads(row["payload_json"]),
            id=row["id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list(self):
        with self.connection() as db:
            return [
                self._read(row)
                for row in db.execute("SELECT * FROM web_jobs ORDER BY created_at DESC LIMIT 50")
            ]

    def update(self, job_id, **fields):
        with self.lock, self.connection() as db:
            job = self._read(db.execute("SELECT * FROM web_jobs WHERE id=?", (job_id,)).fetchone())
            job.update(fields)
            metadata = {
                k: v
                for k, v in fields.items()
                if k
                in (
                    "status",
                    "stage",
                    "current_record",
                    "attempt",
                    "done",
                    "cached",
                    "api_calls",
                    "error",
                )
            }
            db.execute(
                "INSERT INTO web_job_events(job_id,timestamp,event,payload_json) VALUES(?,?,?,?)",
                (job_id, now(), "state_changed", json.dumps(metadata, ensure_ascii=False)),
            )
            db.execute(
                "UPDATE web_jobs SET status=?,updated_at=?,payload_json=? WHERE id=?",
                (job["status"], now(), json.dumps(job, ensure_ascii=False), job_id),
            )

    def get(self, job_id):
        with self.connection() as db:
            job = self._read(db.execute("SELECT * FROM web_jobs WHERE id=?", (job_id,)).fetchone())
        current = job.get("current_record")
        if current and job["status"] == "processing":
            with closing(sqlite3.connect(self.settings.database_path, timeout=5)) as db:
                rows = db.execute(
                    """SELECT event,attempt,payload_json FROM events
                    WHERE record_id=? AND timestamp>=? ORDER BY id DESC LIMIT 12""",
                    (current, job["created_at"]),
                ).fetchall()
            if rows:
                event, attempt, raw = rows[0]
                payload = json.loads(raw)
                job["attempt"] = attempt
                job["stage"] = (
                    "review"
                    if event == "source_validation" and not payload.get("errors")
                    else "validate"
                    if event == "recommendation"
                    else "review"
                    if event == "model_call" and payload.get("role") == "reviewer"
                    else "recommend"
                )
        return job

    def submit(self, raw, filename):
        suffix = Path(filename).suffix.casefold()
        if suffix not in (".csv", ".pdf", ".txt") or not 0 < len(raw) <= MAX_BYTES:
            raise ValueError("Velg PDF, CSV eller TXT, maksimalt 20 MB.")
        self.settings.validate_llm()
        identity = self.identity()
        policy = load_policy(self.settings.policy_path)
        fingerprint = stamp(
            {
                "file": hashlib.sha256(raw).hexdigest(),
                "policy": policy["sha256"],
                "pipeline": pipeline_fingerprint(),
                "reader": hashlib.sha256(
                    Path(__file__).with_name("ingestion.py").read_bytes()
                ).hexdigest(),
                "model": self.settings.model,
                "reviewer": self.settings.reviewer_model,
                "provider": self.settings.provider,
                "endpoint": self.settings.base_url,
                "identity": identity,
                "namespace": self.settings.cache_namespace,
                "confidence": self.settings.min_confidence,
                "context": self.settings.context_tokens,
                "output": self.settings.max_output_tokens,
                "input": self.settings.max_input_characters,
                "attempts": self.settings.max_attempts,
                "calls": self.settings.max_api_calls,
                "effort": self.settings.reasoning_effort,
                "triage": self.triage_stamp(),
            }
        )
        with self.lock, self.connection() as db:
            row = db.execute(
                "SELECT * FROM web_jobs WHERE fingerprint=? AND status!='failed' ORDER BY created_at DESC LIMIT 1",
                (fingerprint,),
            ).fetchone()
            if row:
                db.execute(
                    "INSERT INTO web_job_events(job_id,timestamp,event,payload_json) VALUES(?,?,?,?)",
                    (
                        row["id"],
                        now(),
                        "upload_reused",
                        json.dumps({"filename": Path(filename).name[:200]}),
                    ),
                )
                return self._read(row), True
            job_id = uuid.uuid4().hex
            folder = self.settings.root / "artifacts/uploads" / job_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / ("agenda" + suffix)).write_bytes(raw)
            job = {
                "filename": Path(filename.replace("\\", "/")).name[:200],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "stage": "queued",
                "items": [],
                "total": 0,
                "done": 0,
                "cached": 0,
                "api_calls": 0,
                "error": None,
                "model": self.settings.model,
                "reviewer_model": self.settings.reviewer_model,
                "provider": self.settings.provider,
                "policy_version": policy["version"],
                "policy_sha256": policy["sha256"],
                "fingerprint": fingerprint,
            }
            db.execute(
                "INSERT INTO web_jobs VALUES(?,?,?,?,?,?)",
                (job_id, fingerprint, now(), now(), "queued", json.dumps(job, ensure_ascii=False)),
            )
            db.execute(
                "INSERT INTO web_job_events(job_id,timestamp,event,payload_json) VALUES(?,?,?,?)",
                (
                    job_id,
                    now(),
                    "upload_registered",
                    json.dumps({"sha256": job["sha256"], "filename": job["filename"]}),
                ),
            )
        self.pool.submit(self._run, job_id, raw, filename)
        return self.get(job_id), False

    def _run(self, job_id, raw, filename):
        try:
            self.update(
                job_id,
                status="reading",
                stage="reading" if filename.lower().endswith(".csv") else "extract",
                api_calls=0 if filename.lower().endswith(".csv") else 1,
            )
            prepared, refs, extraction = self.reader(raw, filename, self.settings)
            records = prepared["records"]
            items = [dict(r, result=None, source_ref=refs.get(r["record_id"])) for r in records]
            calls = extraction.get("extraction_calls", 0)
            self.update(
                job_id,
                status="processing",
                stage="recommend",
                items=items,
                total=len(items),
                report=prepared["report"],
                extraction=extraction,
                api_calls=calls,
                current_record=None,
            )
            counters = {"done": 0, "cached": 0, "light_calls": 0, "escalated": 0}
            scores = self._score(records, job_id)
            if scores:
                for item in items:
                    item["triage"] = scores.get(item["record_id"])
                self.update(
                    job_id, items=items, stage="triage", triage_summary=self._summary(items)
                )
                calls = self._run_triaged(job_id, records, items, calls, counters)
            else:
                for index, record in enumerate(records):
                    calls = self._agent(job_id, index, record, items, calls, counters)
            manual = any(i["result"].get("needs_human_review") for i in items)
            self.update(
                job_id,
                status="needs_attention" if manual else "completed",
                stage="done",
                current_record=None,
            )
        except Exception as exc:
            logger.error("Agenda job %s failed (%s)", job_id, type(exc).__name__)
            message = str(exc) if isinstance(exc, ValueError) else provider_error(exc)["message"]
            self.update(job_id, status="failed", stage="failed", error=message, current_record=None)

    def _agent(self, job_id, index, record, items, calls, counters):
        """The existing, audited LangGraph decision for one record (behaviour unchanged)."""
        if self.stop.is_set():
            raise ValueError("Kjøringen ble avbrutt. Last opp filen på nytt for å fortsette.")
        if calls >= self.settings.max_api_calls:
            raise ValueError(
                "Kjøringen nådde modellbudsjettet. Ferdige saker er lagret. Kontakt prosjektansvarlig."
            )
        self.update(job_id, current_record=record["record_id"], stage="recommend", attempt=1)
        summary = self.processor(
            [record],
            db_path=self.settings.database_path,
            mode="llm",
            settings=self.settings,
            limit=1,
            max_api_calls=self.settings.max_api_calls - calls,
        )
        calls += summary["api_calls"]
        with self.connection() as db:
            event_rows = db.execute(
                "SELECT run_key,payload_json FROM events WHERE record_id=? ORDER BY id DESC LIMIT 100",
                (record["record_id"],),
            ).fetchall()
            key = next(
                (
                    e["run_key"]
                    for e in event_rows
                    if json.loads(e["payload_json"]).get("batch_id") == summary["batch_id"]
                ),
                None,
            )
            row = db.execute(
                "SELECT status,attempts,result_json FROM results WHERE run_key=?", (key,)
            ).fetchone()
        result = (
            dict(json.loads(row["result_json"]), status=row["status"], attempts=row["attempts"])
            if row
            else None
        )
        if result is None or result["status"] == "processing":
            raise ValueError(
                "Saken behandles av en annen prosess. Last opp igjen når den er ferdig."
            )
        trace = load_events(self.settings.database_path, result["run_key"])
        with self.lock:
            public = public_result(result, trace)
            if items[index].get("triage"):
                public["trace"] = [triage_event(items[index])] + public["trace"]
                public["check"] = "full"
            items[index]["result"] = public
            items[index]["cached"] = bool(summary["skipped"])
            counters["done"] += 1
            counters["cached"] += bool(summary["skipped"])
            self.update(
                job_id,
                items=items,
                done=counters["done"],
                cached=counters["cached"],
                api_calls=calls,
                light_calls=counters["light_calls"],
            )
        if summary.get("stopped_reason") or result["status"] in ("error", "deferred"):
            raise ValueError(result.get("reason") or "Modellen kunne ikke fullføre kjøringen.")
        return calls

    # ------------------------------------------------------------------ triage + light checks
    def triage_model(self):
        if self._triage is None:
            path = self.settings.triage_model_path
            csv = self.settings.root / "data/real_votes.csv"
            self._triage = False
            if path.exists() and csv.exists():
                try:
                    self._triage = triage_lib.TriageModel.load(path, csv)
                except Exception as exc:  # noqa: BLE001 - a stale model turns triage off, not the app
                    logger.warning("Triage model not loaded (%s)", type(exc).__name__)
        return self._triage or None

    def triage_stamp(self):
        if self._triage_sha is None:
            path = self.settings.triage_model_path
            self._triage_sha = (
                hashlib.sha256(path.read_bytes()).hexdigest() + "|" + LIGHT_VERSION
                if self._triage is not False and path.exists()
                else ""
            )
        return self._triage_sha

    def triage_card(self):
        model = self.triage_model()
        if model is None:
            return {
                "available": False,
                "detail": "Triagemodellen er ikke trent. Kjør python run.py --cli triage-train.",
            }
        return dict(model.card(), available=True, light_workers=self.settings.light_workers)

    def _event(self, job_id, event, payload):
        with self.connection() as db:
            db.execute(
                "INSERT INTO web_job_events(job_id,timestamp,event,payload_json) VALUES(?,?,?,?)",
                (job_id, now(), event, json.dumps(payload, ensure_ascii=False)),
            )

    def _score(self, records, job_id):
        model = self.triage_model()
        if model is None or not records:
            return {}
        try:
            scores = model.score(records)
        except Exception as exc:  # noqa: BLE001 - without scores every item goes to the full agent
            logger.warning("Triage failed (%s)", type(exc).__name__)
            self._event(job_id, "triage_failed", {"error": type(exc).__name__})
            return {}
        self._event(
            job_id,
            "triage",
            {
                "model": model.b["version"],
                "flagged": [k for k, v in scores.items() if v["flagged"]],
                "thresholds": model.b["thresholds"],
            },
        )
        return scores

    def _summary(self, items):
        model = self.triage_model()
        flagged = [i for i in items if (i.get("triage") or {}).get("flagged")]
        return {
            "model": model.b["version"] if model else None,
            "items": len(items),
            "flagged": len(flagged),
            "light_workers": self.settings.light_workers,
            "thresholds": model.b["thresholds"] if model else None,
        }

    def _llm(self, instructions, payload, schema, fallback):
        if self.settings.provider != "ollama":
            return dict(fallback, failed=True, skipped="provider"), 0
        started = time.perf_counter()
        out, failed = triage_lib.safe_llm(
            lambda: triage_lib.ollama_json(self.settings, instructions, payload, schema), fallback
        )
        return dict(out, failed=failed, model=self.settings.model), int(
            (time.perf_counter() - started) * 1000
        )

    def _light_check(self, record, scores, catalogue):
        out, ms = self._llm(
            triage_lib.CHECK_INSTRUCTIONS,
            triage_lib.llm_payload(record, scores, catalogue) + self._rules_text(record),
            triage_lib.CHECK_SCHEMA,
            {
                "decision": "ESCALATE",
                "guideline": "none",
                "reason": "Light check returned no valid answer; sent to full review.",
                "confidence": 0.0,
            },
        )
        return dict(out, duration_ms=ms)

    def policy(self):
        return load_policy(self.settings.policy_path)

    def _rules_text(self, record):
        rules = retrieve(record, self.policy())
        if not rules:
            return ""
        return "\nCurated NBIM policy rules that may apply (team paraphrases): " + " | ".join(
            f"{r['id']}: {r['text']}" for r in rules
        )

    def _note(self, record, scores, catalogue):
        out, ms = self._llm(
            triage_lib.NOTE_INSTRUCTIONS,
            triage_lib.llm_payload(record, scores, catalogue) + self._rules_text(record),
            triage_lib.NOTE_SCHEMA,
            {
                "guideline": scores.get("suggested_guideline") or "none",
                "justification": "",
                "confidence": 0.0,
            },
        )
        return dict(out, duration_ms=ms)

    def _run_triaged(self, job_id, records, items, calls, counters):
        """Flagged items go to the full agent, highest risk first. Every other item gets a light,
        parallel agent check; a failed or doubtful check escalates the item to the full agent."""
        catalogue = self.triage_model().b["catalogue"]
        flagged = sorted(
            (i for i, item in enumerate(items) if item["triage"] and item["triage"]["flagged"]),
            key=lambda i: -items[i]["triage"]["risk"],
        )
        unscored = [i for i, item in enumerate(items) if not item["triage"]]
        low = [
            i for i, item in enumerate(items) if item["triage"] and not item["triage"]["flagged"]
        ]
        # The light path must never bypass the agent's safety gate: injection-like or oversized
        # text goes to the full flow, where the gate sends it to a human without a model call.
        guarded = [
            i
            for i in low
            if injection_signals(records[i]["proposal_text"])
            or len(records[i]["proposal_text"]) > self.settings.max_input_characters
        ]
        for i in guarded:
            items[i]["safety_routed"] = True
            self._event(job_id, "safety_routed", {"record_id": records[i]["record_id"]})
        # Items an explicit curated rule covers (its pattern matches, inside the policy's date
        # window) belong to the full agent, which applies that rule; the light check never overrides it.
        covered = {}
        for i in low:
            if i not in guarded and (rule := policy_rule_hit(records[i], self.policy())):
                covered[i] = rule
                items[i]["policy_routed"] = rule
                self._event(
                    job_id, "policy_routed", {"record_id": records[i]["record_id"], "rule": rule}
                )
        low = [i for i in low if i not in guarded and i not in covered]
        # Three phases that never overlap, so the agent and the light checks never compete for the
        # local model (concurrent requests with different schemas stalled Ollama). This also keeps
        # weak hardware predictable: only light checks run in parallel, the agent runs alone.
        queue = deque(flagged + guarded + list(covered) + unscored)
        calls = self._drain(job_id, queue, records, items, calls, counters)  # 1: flagged first
        jobs = [("check", i) for i in low] + [("note", i) for i in flagged]
        with ThreadPoolExecutor(
            max_workers=self.settings.light_workers, thread_name_prefix="light"
        ) as pool:  # 2: light checks (+ notes for flagged items) in parallel
            fn = {"check": self.light_checker, "note": self.note_writer}
            futures = {
                pool.submit(fn[kind], records[i], items[i]["triage"], catalogue): (kind, i)
                for kind, i in jobs
            }
            pending = set(futures)
            while pending:
                if self.stop.is_set():
                    raise ValueError(
                        "Kjøringen ble avbrutt. Last opp filen på nytt for å fortsette."
                    )
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    self._harvest(job_id, future, futures[future], records, items, queue, counters)
        return self._drain(job_id, queue, records, items, calls, counters)  # 3: escalated items

    def _drain(self, job_id, queue, records, items, calls, counters):
        while queue:
            index = queue.popleft()
            calls = self._agent(job_id, index, records[index], items, calls, counters)
        return calls

    def _harvest(self, job_id, future, kind_index, records, items, queue, counters):
        kind, index = kind_index
        try:
            out = future.result()
        except Exception:  # noqa: BLE001 - defensive: an unexpected error escalates
            out = {
                "decision": "ESCALATE",
                "guideline": "none",
                "reason": "",
                "confidence": 0.0,
                "failed": True,
            }
        record, item = records[index], items[index]
        with self.lock:
            if kind == "note":
                item["model_note"] = out
                self.update(job_id, items=items)
                return
            counters["light_calls"] += 0 if out.get("skipped") else 1
            item["light_check"] = out
            self._event(
                job_id,
                "light_check",
                {
                    "record_id": record["record_id"],
                    "decision": out.get("decision"),
                    "guideline": out.get("guideline"),
                    "failed": bool(out.get("failed")),
                    "duration_ms": out.get("duration_ms"),
                },
            )
            # same bar as the full agent: an unsure "follow the board" is not a decision
            unsure = float(out.get("confidence") or 0.0) < self.settings.min_confidence
            if out.get("failed") or out.get("decision") != "FOLLOW_BOARD" or unsure:
                out["escalation_reason"] = (
                    "failed"
                    if out.get("failed")
                    else "doubt"
                    if out.get("decision") != "FOLLOW_BOARD"
                    else "low_confidence"
                )
                counters["escalated"] += 1
                item["escalated"] = True
                queue.append(index)
                self.update(
                    job_id,
                    items=items,
                    light_calls=counters["light_calls"],
                    escalated=counters["escalated"],
                )
                return
            item["result"] = light_result(
                record, item["triage"], out, self.triage_model().b["catalogue"]
            )
            counters["done"] += 1
            self.update(
                job_id,
                items=items,
                done=counters["done"],
                light_calls=counters["light_calls"],
                escalated=counters["escalated"],
            )


def policy_rule_hit(record, policy):
    """Id of a curated rule whose explicit pattern matches this item (date window respected)."""
    for rule in retrieve(record, policy, top_k=len(policy["rules"])):
        for pattern in rule.get("demo_patterns", []):
            if re.fullmatch(pattern["pattern"], record["proposal_text"], re.IGNORECASE):
                return rule["id"]
    return None


def triage_event(item):
    t = item["triage"]
    check = item.get("light_check")
    detail = f"Risiko {t['risk']:.0%} · {t['lane_label']} · " + (
        "flagget for full vurdering" if t["flagged"] else "lav risiko"
    )
    if check:
        detail += f" · lett kontroll: {check.get('decision')} ({check.get('reason', '')})"
    return {"event": "triage", "attempt": 1, "timestamp": now(), "detail": detail, "accepted": True}


def light_result(record, scores, check, catalogue):
    guideline = str(check.get("guideline") or "").strip()
    citations = (
        [
            {
                "policy_id": guideline,
                "locator": "NBIMs standardbegrunnelse",
                "source_url": NBIM_VOTING_URL,
                "policy_excerpt": catalogue[guideline]["text"][:400],
                "evidence_quote": str(record.get("proposal_text", ""))[:300],
            }
        ]
        if guideline in catalogue
        else []
    )
    stamped = now()
    return {
        "run_key": "light:"
        + stamp({"evidence": record.get("evidence_hash"), "check": check, "v": LIGHT_VERSION})[:32],
        "status": "verified",
        "vote": scores["follow_board_vote"],
        "confidence": float(check.get("confidence") or 0.0),
        "reason": check.get("reason") or "Ingen indikasjon på brudd med retningslinjene.",
        "review_reason": (
            f"Lett agentkontroll. Triagemodellen ga lav risiko ({scores['risk']:.0%}, terskel "
            f"{scores['threshold']:.0%}); agenten fant ingen grunn til full vurdering. "
            "Stemmen følger styrets anbefaling."
        ),
        "citations": citations,
        "attempts": 1,
        "retries": 0,
        "needs_human_review": False,
        "fallback_type": None,
        "duration_ms": int(check.get("duration_ms") or 0),
        "updated_at": stamped,
        "check": "light",
        "trace": [
            triage_event({"triage": scores, "light_check": check}),
            {
                "event": "light_check",
                "attempt": 1,
                "timestamp": stamped,
                "detail": f"{check.get('decision')} · {guideline or 'ingen retningslinje'} · {check.get('reason', '')}",
                "accepted": True,
            },
        ],
    }


def public_result(result, events):
    allowed = (
        "run_key",
        "status",
        "vote",
        "confidence",
        "reason",
        "review_reason",
        "citations",
        "attempts",
        "retries",
        "needs_human_review",
        "fallback_type",
        "duration_ms",
        "updated_at",
    )
    value = {k: result.get(k) for k in allowed}
    if result["status"] != "verified":
        value["confidence"] = None
    value["trace"] = [
        {
            "event": e["event"],
            "attempt": e["attempt"],
            "timestamp": e["timestamp"],
            "detail": event_detail(e),
            "accepted": e["payload"].get("accepted"),
        }
        for e in events
        if e["event"]
        in (
            "attempt_started",
            "recommendation",
            "source_validation",
            "verification",
            "finalized",
            "cache_hit",
        )
    ]
    return value


def event_detail(event):
    payload = event["payload"]
    if event["event"] != "recommendation":
        return payload.get("reason") or "; ".join(payload.get("errors", [])) or ""
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        return "Agenten leverte et forslag som ikke kunne godkjennes."
    score = candidate.get("confidence")
    formatted = (
        f"{score:.0%}"
        if type(score) in (float, int) and math.isfinite(score) and 0 <= score <= 1
        else "ukjent"
    )
    citations = candidate.get("citations")
    ids = (
        ", ".join(
            c.get("policy_id", "")
            for c in citations
            if isinstance(c, dict) and isinstance(c.get("policy_id"), str)
        )
        if isinstance(citations, list)
        else ""
    )
    return f"Foreløpig: {candidate.get('vote', 'ukjent')} · egen konfidens {formatted}. Retningslinjer: {ids or 'ingen'}. {candidate.get('reason', '')}"
