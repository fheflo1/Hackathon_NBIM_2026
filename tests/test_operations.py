import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from test_workflow import FakeAgents

from nbim_flow.config import ConfigurationError, Settings
from nbim_flow.data import safe_record
from nbim_flow.diagnostics import initialize_env
from nbim_flow.monitoring import input_shift, operational_snapshot
from nbim_flow.store import AuditStore, LeaseLostError, load_batches, load_results
from nbim_flow.workflow import process_records

ROOT = Path(__file__).resolve().parents[1]


def records(n=1):
    return [
        safe_record(
            {
                "source": "upload",
                "company": "DEMO",
                "meeting_id": f"m{i}",
                "item_no": "1",
                "meeting_date": "2025-06-01",
                "proposal_text": "Require an independent chair",
            }
        )
        for i in range(n)
    ]


class SettingsTests(unittest.TestCase):
    def test_local_needs_no_api_key(self):
        settings = Settings.from_env(ROOT, environ={"LLM_MODEL": "local:7b"})
        settings.validate_llm()
        self.assertEqual(settings.provider, "ollama")
        self.assertEqual(settings.model, "local:7b")

    def test_secrets_not_in_public_configuration_or_repr(self):
        settings = Settings.from_env(ROOT, environ={"OPENAI_API_KEY": "SECRET"})
        self.assertNotIn("SECRET", repr(settings))
        self.assertNotIn("SECRET", json.dumps(settings.public_info()))

    def test_remote_ollama_and_cloud_tags_rejected(self):
        for env in (
            {"LLM_BASE_URL": "https://example.com"},
            {"LLM_MODEL": "anything:cloud"},
            {"LLM_BASE_URL": "http://password@localhost:11434"},
            {"NBIM_MAX_ATTEMPTS": "6"},
        ):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(ROOT, environ=env)

    def test_initialize_does_not_overwrite_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text("LLM_PROVIDER=ollama\n")
            self.assertTrue(initialize_env(root)["created"])
            (root / ".env").write_text("KEEP_ME")
            self.assertFalse(initialize_env(root)["created"])
            self.assertEqual((root / ".env").read_text(), "KEEP_ME")


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "audit.sqlite"
        self.settings = Settings.from_env(ROOT, environ={})

    def tearDown(self):
        self.tmp.cleanup()

    def run_cases(self, rows, **kwargs):
        return process_records(rows, db_path=self.db, settings=self.settings, **kwargs)

    def test_budget_stops_before_review_and_resume_preserves_attempts(self):
        summary = self.run_cases(records(), mode="llm", agents=FakeAgents(), max_api_calls=1)
        self.assertEqual(
            (summary["api_calls"], summary["deferred"], summary["stopped_reason"]),
            (1, 1, "call_budget"),
        )
        self.assertEqual(load_results(self.db)[0]["attempts"], 1)
        self.run_cases(records(), mode="llm", agents=FakeAgents(), max_api_calls=2)
        result = load_results(self.db)[0]
        self.assertEqual((result["status"], result["attempts"]), ("verified", 2))

    def test_circuit_breaker_stops_after_three_failed_cases(self):
        agents = FakeAgents(fail=True)
        summary = self.run_cases(records(10), mode="llm", agents=agents)
        self.assertEqual(
            (agents.calls, summary["errors"], summary["stopped_reason"]), (3, 3, "circuit_breaker")
        )
        self.assertEqual(len(load_results(self.db)), 3)
        self.assertEqual(load_batches(self.db)[0]["status"], "stopped")

    def test_auth_error_stops_after_first_case(self):
        class AuthError(RuntimeError):
            status_code = 401

        class Failing(FakeAgents):
            def propose(self, *args, **kwargs):
                self.calls += 1
                raise AuthError("SECRET do not log")

        agents = Failing()
        summary = self.run_cases(records(10), mode="llm", agents=agents)
        self.assertEqual((agents.calls, summary["stopped_reason"]), (1, "authentication"))
        self.assertNotIn("SECRET", self.db.read_bytes().decode("latin1"))

    def test_human_review_preserves_machine_result(self):
        self.run_cases(records())
        original = load_results(self.db)[0]
        store = AuditStore(self.db)
        try:
            store.review(
                original["run_key"],
                "Analytiker",
                "MOT",
                "Supplerende dokumentasjon gir en annen vurdering.",
            )
        finally:
            store.close()
        result = load_results(self.db)[0]
        self.assertEqual(result["vote"], original["vote"])
        self.assertEqual(result["effective_vote"], "MOT")
        self.assertFalse(result["review_pending"])
        self.assertEqual(operational_snapshot(self.db, "demo")["human_reviewed"], 1)

    def test_stale_worker_cannot_overwrite_new_owner(self):
        first, second = AuditStore(self.db), AuditStore(self.db)
        try:
            first.claim("key", {"record_id": "id"})
            with first.db:
                first.db.execute("UPDATE results SET lease_until=0")
            second.claim("key", {"record_id": "id"})
            with self.assertRaises(LeaseLostError):
                first.start_attempt("key", 1)
            with self.assertRaises(LeaseLostError):
                first.finish(
                    {"run_key": "key", "record_id": "id", "status": "verified", "attempts": 1}
                )
        finally:
            first.close()
            second.close()

    def test_v1_database_migrates_without_losing_results(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute(
                "CREATE TABLE results (run_key TEXT PRIMARY KEY,record_id TEXT,status TEXT,attempts INTEGER,lease_until REAL,result_json TEXT,updated_at TEXT)"
            )
            db.execute(
                "INSERT INTO results VALUES(?,?,?,?,?,?,?)",
                ("old", "id", "human_review", 0, 0, json.dumps({"record_id": "id"}), "2025"),
            )
        store = AuditStore(self.db)
        store.close()
        self.assertEqual(len(load_results(self.db)), 1)

    def test_shift_requires_enough_rows_and_measures_changed_topics(self):
        self.assertFalse(input_shift([{"topic": "a"}], {"topics": {"a": 20}})["measured"])
        self.assertEqual(
            input_shift([{"topic": "b"}] * 30, {"topics": {"a": 30}})["topic_total_variation"], 1
        )


if __name__ == "__main__":
    unittest.main()
