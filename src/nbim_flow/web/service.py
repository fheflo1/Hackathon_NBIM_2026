"""Durable upload queue. The existing, audited LangGraph owns each vote decision."""

import hashlib
import json
import logging
import math
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from ..local_model import model_identity
from ..operations import provider_error
from ..policy import load_policy
from ..store import AuditStore, load_events, now
from ..workflow import pipeline_fingerprint, process_records
from .ingestion import MAX_BYTES, read_agenda

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "needs_attention", "failed"}


def stamp(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class AgendaService:
    def __init__(self, settings, processor=process_records, reader=read_agenda, identity=None):
        self.settings, self.processor, self.reader = settings, processor, reader
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
            done, cached = 0, 0
            for index, record in enumerate(records):
                if self.stop.is_set():
                    raise ValueError(
                        "Kjøringen ble avbrutt. Last opp filen på nytt for å fortsette."
                    )
                if calls >= self.settings.max_api_calls:
                    raise ValueError(
                        "Kjøringen nådde modellbudsjettet. Ferdige saker er lagret. Kontakt prosjektansvarlig."
                    )
                self.update(
                    job_id, current_record=record["record_id"], stage="recommend", attempt=1
                )
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
                    dict(
                        json.loads(row["result_json"]),
                        status=row["status"],
                        attempts=row["attempts"],
                    )
                    if row
                    else None
                )
                if result is None or result["status"] == "processing":
                    raise ValueError(
                        "Saken behandles av en annen prosess. Last opp igjen når den er ferdig."
                    )
                trace = load_events(self.settings.database_path, result["run_key"])
                items[index]["result"] = public_result(result, trace)
                items[index]["cached"] = bool(summary["skipped"])
                done += 1
                cached += bool(summary["skipped"])
                self.update(job_id, items=items, done=done, cached=cached, api_calls=calls)
                if summary.get("stopped_reason") or result["status"] in ("error", "deferred"):
                    raise ValueError(
                        result.get("reason") or "Modellen kunne ikke fullføre kjøringen."
                    )
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
