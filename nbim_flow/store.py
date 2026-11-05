"""SQLite audit events and atomic case claims for the local prototype."""

import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class AuditStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS results (
                run_key TEXT PRIMARY KEY, record_id TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0,
                result_json TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                run_key TEXT NOT NULL, record_id TEXT NOT NULL,
                attempt INTEGER NOT NULL, event TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS event_run ON events(run_key, id);
        """)

    def event(self, run_key, record_id, attempt, event, payload):
        with self.db:
            self.db.execute("INSERT INTO events(timestamp,run_key,record_id,attempt,event,payload_json) VALUES(?,?,?,?,?,?)",
                            (now(), run_key, record_id, attempt, event, json.dumps(payload, ensure_ascii=False)))

    def claim(self, run_key, initial):
        """A 10-minute lease exceeds the bounded 5 x 2 x 45-second API budget.

        A crashed process can be resumed after lease expiry. Attempts are
        persisted before each external call, so a restart cannot reset the cap.
        """
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM results WHERE run_key=?", (run_key,)).fetchone()
            if row and row["status"] not in ("processing", "error"):
                return False, row["attempts"], "cached"
            if row and row["lease_until"] > time.time():
                return False, row["attempts"], "busy"
            attempts = row["attempts"] if row else 0
            self.db.execute("""INSERT INTO results VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(run_key) DO UPDATE SET status='processing', lease_until=excluded.lease_until,
                updated_at=excluded.updated_at""",
                (run_key, initial["record_id"], "processing", attempts, time.time() + 600,
                 json.dumps(initial, ensure_ascii=False), now()))
            return True, attempts, "resumed" if row else "new"

    def start_attempt(self, run_key, attempt):
        with self.db:
            self.db.execute("UPDATE results SET attempts=?,lease_until=?,updated_at=? WHERE run_key=?",
                            (attempt, time.time() + 600, now(), run_key))

    def finish(self, result):
        result["updated_at"] = now()
        with self.db:
            self.db.execute("UPDATE results SET status=?,attempts=?,lease_until=0,result_json=?,updated_at=? WHERE run_key=?",
                            (result["status"], result["attempts"], json.dumps(result, ensure_ascii=False),
                             result["updated_at"], result["run_key"]))
            self.db.execute("INSERT INTO events(timestamp,run_key,record_id,attempt,event,payload_json) VALUES(?,?,?,?,?,?)",
                            (result["updated_at"], result["run_key"], result["record_id"],
                             result["attempts"], "finalized", json.dumps(result, ensure_ascii=False)))

    def close(self):
        self.db.close()


def load_results(db_path="artifacts/audit.sqlite"):
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM results ORDER BY updated_at DESC,run_key").fetchall()
        return [dict(json.loads(r["result_json"]), status=r["status"], attempts=r["attempts"], retries=max(0, r["attempts"] - 1),
                     updated_at=r["updated_at"]) for r in rows]


def load_events(db_path="artifacts/audit.sqlite", run_key=None):
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory = sqlite3.Row
        query = "SELECT * FROM events" + (" WHERE run_key=?" if run_key else "") + " ORDER BY id"
        rows = db.execute(query, (run_key,) if run_key else ()).fetchall()
        return [dict(id=r["id"], timestamp=r["timestamp"], run_key=r["run_key"],
                     record_id=r["record_id"], attempt=r["attempt"], event=r["event"],
                     payload=json.loads(r["payload_json"])) for r in rows]
