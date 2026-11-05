"""Versioned SQLite audit store, fenced leases, batch telemetry and human review."""

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class LeaseLostError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)


class AuditStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.tokens = {}
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS results (
                run_key TEXT PRIMARY KEY, record_id TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0,
                result_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                owner_token TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                run_key TEXT NOT NULL, record_id TEXT NOT NULL,
                attempt INTEGER NOT NULL, event TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS event_run ON events(run_key,id);
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                status TEXT NOT NULL, metadata_json TEXT NOT NULL, summary_json TEXT
            );
            CREATE TABLE IF NOT EXISTS human_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_key TEXT NOT NULL,
                reviewed_at TEXT NOT NULL, reviewer TEXT NOT NULL,
                vote TEXT NOT NULL, reason TEXT NOT NULL,
                FOREIGN KEY(run_key) REFERENCES results(run_key)
            );
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(results)")}
        with self.db:
            if "owner_token" not in columns:
                self.db.execute(
                    "ALTER TABLE results ADD COLUMN owner_token TEXT NOT NULL DEFAULT ''"
                )
            self.db.execute("PRAGMA user_version=2")

    def event(self, run_key, record_id, attempt, event, payload):
        with self.db:
            self._event(run_key, record_id, attempt, event, payload)

    def _event(self, run_key, record_id, attempt, event, payload):
        self.db.execute(
            "INSERT INTO events(timestamp,run_key,record_id,attempt,event,payload_json) VALUES(?,?,?,?,?,?)",
            (now(), run_key, record_id, attempt, event, json.dumps(payload, ensure_ascii=False)),
        )

    def claim(self, run_key, initial):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM results WHERE run_key=?", (run_key,)).fetchone()
            if row and row["status"] not in ("processing", "error", "deferred"):
                return False, row["attempts"], "cached"
            if row and row["lease_until"] > time.time():
                return False, row["attempts"], "busy"
            attempts = row["attempts"] if row else 0
            token = uuid.uuid4().hex
            self.db.execute(
                """INSERT INTO results
                (run_key,record_id,status,attempts,lease_until,result_json,updated_at,owner_token)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_key) DO UPDATE SET
                status='processing',lease_until=excluded.lease_until,updated_at=excluded.updated_at,
                owner_token=excluded.owner_token""",
                (
                    run_key,
                    initial["record_id"],
                    "processing",
                    attempts,
                    time.time() + 600,
                    json.dumps(initial, ensure_ascii=False),
                    now(),
                    token,
                ),
            )
            self.tokens[run_key] = token
            return True, attempts, "resumed" if row else "new"

    def start_attempt(self, run_key, attempt):
        with self.db:
            count = self.db.execute(
                """UPDATE results SET attempts=?,lease_until=?,updated_at=?
                WHERE run_key=? AND owner_token=? AND status='processing' """,
                (attempt, time.time() + 600, now(), run_key, self.tokens.get(run_key, "")),
            ).rowcount
            if count != 1:
                raise LeaseLostError(
                    "En annen prosess har overtatt saken; denne prosessen stoppes."
                )

    def finish(self, result):
        result["updated_at"] = now()
        with self.db:
            count = self.db.execute(
                """UPDATE results SET status=?,attempts=?,lease_until=0,
                result_json=?,updated_at=? WHERE run_key=? AND owner_token=? AND status='processing' """,
                (
                    result["status"],
                    result["attempts"],
                    json.dumps(result, ensure_ascii=False),
                    result["updated_at"],
                    result["run_key"],
                    self.tokens.get(result["run_key"], ""),
                ),
            ).rowcount
            if count != 1:
                raise LeaseLostError(
                    "Saken er overtatt av en annen prosess; resultatet ble ikke skrevet."
                )
            self._event(
                result["run_key"], result["record_id"], result["attempts"], "finalized", result
            )

    def start_batch(self, batch_id, metadata):
        with self.db:
            self.db.execute(
                "INSERT INTO batches VALUES(?,?,NULL,'running',?,NULL)",
                (batch_id, now(), json.dumps(metadata, ensure_ascii=False)),
            )

    def finish_batch(self, batch_id, summary, status="completed"):
        with self.db:
            self.db.execute(
                "UPDATE batches SET finished_at=?,status=?,summary_json=? WHERE batch_id=?",
                (now(), status, json.dumps(summary, ensure_ascii=False), batch_id),
            )

    def review(self, run_key, reviewer, vote, reason):
        reviewer, reason = reviewer.strip(), reason.strip()
        if (
            vote not in ("FOR", "MOT", "AVSTÅ")
            or not 1 <= len(reviewer) <= 100
            or not 10 <= len(reason) <= 5000
        ):
            raise ValueError("Oppgi navn, gyldig stemme og en begrunnelse på 10–5000 tegn.")
        with self.db:
            row = self.db.execute("SELECT * FROM results WHERE run_key=?", (run_key,)).fetchone()
            if row is None or row["status"] == "processing":
                raise ValueError("Saken finnes ikke eller er fortsatt under behandling.")
            stamp = now()
            self.db.execute(
                "INSERT INTO human_reviews(run_key,reviewed_at,reviewer,vote,reason) VALUES(?,?,?,?,?)",
                (run_key, stamp, reviewer, vote, reason),
            )
            self._event(
                run_key,
                row["record_id"],
                row["attempts"],
                "human_review",
                {"reviewer": reviewer, "vote": vote, "reason": reason, "reviewed_at": stamp},
            )

    def close(self):
        self.db.close()


def load_results(db_path="artifacts/audit.sqlite", latest=False):
    if not Path(db_path).exists():
        return []
    with closing(_read(db_path)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM results ORDER BY updated_at DESC,run_key").fetchall()
        reviews = {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='human_reviews'").fetchone():
            for r in db.execute("SELECT * FROM human_reviews ORDER BY id DESC"):
                reviews.setdefault(r["run_key"], dict(r))
        outcomes, seen = [], set()
        for row in rows:
            item = dict(
                json.loads(row["result_json"]),
                status=row["status"],
                attempts=row["attempts"],
                retries=max(0, row["attempts"] - 1),
                updated_at=row["updated_at"],
            )
            identity = (item["record_id"], item.get("mode"))
            if latest and identity in seen:
                continue
            seen.add(identity)
            human = reviews.get(row["run_key"])
            item["human_review"] = human
            item["effective_vote"] = human["vote"] if human else item.get("vote")
            item["review_pending"] = bool(item.get("needs_human_review")) and human is None
            outcomes.append(item)
        return outcomes


def load_events(db_path="artifacts/audit.sqlite", run_key=None):
    if not Path(db_path).exists():
        return []
    with closing(_read(db_path)) as db:
        db.row_factory = sqlite3.Row
        query = "SELECT * FROM events" + (" WHERE run_key=?" if run_key else "") + " ORDER BY id"
        rows = db.execute(query, (run_key,) if run_key else ()).fetchall()
        return [
            dict(
                id=r["id"],
                timestamp=r["timestamp"],
                run_key=r["run_key"],
                record_id=r["record_id"],
                attempt=r["attempt"],
                event=r["event"],
                payload=json.loads(r["payload_json"]),
            )
            for r in rows
        ]


def load_batches(db_path="artifacts/audit.sqlite", limit=100):
    if not Path(db_path).exists():
        return []
    with closing(_read(db_path)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='batches'").fetchone():
            return []
        return [
            dict(
                batch_id=r["batch_id"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                status=r["status"],
                metadata=json.loads(r["metadata_json"]),
                summary=json.loads(r["summary_json"]) if r["summary_json"] else None,
            )
            for r in db.execute("SELECT * FROM batches ORDER BY started_at DESC LIMIT ?", (limit,))
        ]
