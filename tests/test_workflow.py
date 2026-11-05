import json
import tempfile
import unittest
from pathlib import Path

from nbim_flow.agents import demo_propose, validate_decision
from nbim_flow.data import prepare_csv, safe_record
from nbim_flow.policy import load_policy, retrieve
from nbim_flow.store import AuditStore
from nbim_flow.workflow import load_events, load_results, process_records

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policies/nbim_2025.json"


def agenda(text="Require an independent chair", **kwargs):
    return safe_record(
        dict(
            source="upload",
            company="DEMO",
            meeting_id="meeting-1",
            item_no="1",
            meeting_date="2025-06-01",
            proposal_text=text,
            **kwargs,
        )
    )


class FakeAgents:
    def __init__(self, reject=0, fail=False, fabricate=False, missing=False):
        self.calls = 0
        self.reviews = 0
        self.reject = reject
        self.fail = fail
        self.fabricate = fabricate
        self.missing = missing

    def propose(self, record, rules, feedback=""):
        self.calls += 1
        if self.fail:
            raise ConnectionError("not logged")
        decision = demo_propose(record, rules)
        if self.fabricate:
            decision["citations"][0]["policy_id"] = "INVENTED"
        return decision

    def review(self, record, rules, candidate):
        self.reviews += 1
        return {
            "accepted": self.reviews > self.reject and not self.missing,
            "retryable": not self.missing,
            "reason": "Kontrollerte kilde og begrunnelse",
        }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "audit.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def run_cases(self, records, **kwargs):
        return process_records(records, db_path=self.db, policy_path=POLICY, **kwargs)

    def test_demo_end_to_end_and_idempotency(self):
        records = prepare_csv(ROOT / "data/demo_agenda.csv", "upload")["records"]
        summary = self.run_cases(records)
        self.assertEqual(summary["processed"], 4)
        results = load_results(self.db)
        self.assertEqual(
            sorted(r["vote"] for r in results), sorted(["FOR", "MOT", "AVSTÅ", "AVSTÅ"])
        )
        self.assertTrue(all(r["needs_human_review"] for r in results))
        self.assertEqual(sum(r["fallback_type"] == "prompt_injection" for r in results), 1)
        self.assertEqual(self.run_cases(records)["skipped"], 4)
        self.assertEqual(len(load_results(self.db)), 4)
        self.assertEqual(sum(e["event"] == "cache_hit" for e in load_events(self.db)), 4)

    def test_five_total_attempts_means_four_retries_then_handoff(self):
        agents = FakeAgents(reject=99)
        self.run_cases([agenda()], mode="llm", agents=agents)
        result = load_results(self.db)[0]
        self.assertEqual((agents.calls, agents.reviews), (5, 5))
        self.assertEqual((result["attempts"], result["retries"]), (5, 4))
        self.assertEqual((result["vote"], result["status"]), ("AVSTÅ", "human_review"))
        self.assertTrue(result["needs_human_review"])

    def test_revision_then_accept(self):
        agents = FakeAgents(reject=1)
        self.run_cases([agenda()], mode="llm", agents=agents)
        result = load_results(self.db)[0]
        self.assertEqual((result["attempts"], result["status"]), (2, "verified"))
        self.assertFalse(result["needs_human_review"])
        self.assertEqual(result["citations"][0]["kind"], "curated_paraphrase")

    def test_labels_do_not_invalidate_case_but_evidence_does(self):
        record = agenda()
        self.run_cases([record])
        self.assertEqual(
            self.run_cases([dict(record, nbim_vote="MOT", rationale_text="secret")])["skipped"], 1
        )
        self.run_cases([dict(record, proposal_text="Introduce a staggered board")])
        results = load_results(self.db)
        self.assertEqual(len(results), 2)
        self.assertEqual(len({r["record_id"] for r in results}), 1)
        self.assertEqual(len({r["run_key"] for r in results}), 2)
        self.assertTrue(all("nbim_vote" not in r for r in results))

    def test_policy_change_invalidates_watermark(self):
        record = agenda()
        self.run_cases([record])
        path = Path(self.temp.name) / "policy.json"
        policy = json.loads(POLICY.read_text())
        policy["version"] += "-updated"
        path.write_text(json.dumps(policy))
        process_records([record], db_path=self.db, policy_path=path)
        self.assertEqual(len(load_results(self.db)), 2)

    def test_api_error_not_cached_as_success(self):
        first = FakeAgents(fail=True)
        self.assertEqual(self.run_cases([agenda()], mode="llm", agents=first)["errors"], 1)
        self.assertEqual(load_results(self.db)[0]["status"], "error")
        second = FakeAgents()
        self.run_cases([agenda()], mode="llm", agents=second)
        result = load_results(self.db)[0]
        self.assertEqual((result["attempts"], result["status"]), (2, "verified"))

    def test_missing_evidence_stops_early(self):
        agents = FakeAgents(missing=True)
        self.run_cases([agenda()], mode="llm", agents=agents)
        self.assertEqual(agents.calls, 1)
        self.assertEqual(load_results(self.db)[0]["vote"], "AVSTÅ")

    def test_fabricated_policy_never_reaches_semantic_reviewer(self):
        agents = FakeAgents(fabricate=True)
        self.run_cases([agenda()], mode="llm", agents=agents)
        self.assertEqual(agents.calls, 5)
        self.assertEqual(agents.reviews, 0)
        self.assertTrue(load_results(self.db)[0]["needs_human_review"])

    def test_future_policy_cannot_be_used_for_earlier_or_later_year(self):
        agents = FakeAgents()
        records = [
            dict(agenda(), meeting_id="m2024", meeting_date="2024-06-01"),
            dict(agenda(), meeting_id="m2026", meeting_date="2026-06-01"),
        ]
        self.run_cases(records, mode="llm", agents=agents)
        self.assertEqual(agents.calls, 0)
        self.assertTrue(
            all(r["fallback_type"] == "policy_unavailable" for r in load_results(self.db))
        )

    def test_new_batch_moves_past_cached_cases(self):
        records = [dict(agenda(), item_no=str(i)) for i in range(3)]
        self.assertEqual(self.run_cases(records, limit=1)["processed"], 1)
        summary = self.run_cases(records, limit=1)
        self.assertEqual((summary["processed"], summary["skipped"]), (1, 1))
        self.assertEqual(len(load_results(self.db)), 2)

    def test_store_atomic_claim_and_expired_lease_retains_attempts(self):
        initial = {"record_id": "case"}
        first, second = AuditStore(self.db), AuditStore(self.db)
        try:
            self.assertTrue(first.claim("key", initial)[0])
            first.start_attempt("key", 3)
            self.assertEqual(second.claim("key", initial), (False, 3, "busy"))
            with first.db:
                first.db.execute("UPDATE results SET lease_until=0 WHERE run_key='key'")
            self.assertEqual(second.claim("key", initial), (True, 3, "resumed"))
        finally:
            first.close()
            second.close()

    def test_fabricated_evidence_quote_rejected(self):
        record = agenda()
        rules = retrieve(record, load_policy(POLICY))
        candidate = demo_propose(record, rules)
        candidate["citations"][0]["evidence_quote"] = "CEO is independent"
        self.assertTrue(validate_decision(candidate, record, rules))

    def test_malformed_policy_id_is_a_validation_error(self):
        record = agenda()
        rules = retrieve(record, load_policy(POLICY))
        candidate = demo_propose(record, rules)
        candidate["citations"][0]["policy_id"] = ["malformed"]
        self.assertTrue(validate_decision(candidate, record, rules))

    def test_invalid_calendar_date_rejected_at_public_boundary(self):
        with self.assertRaises(ValueError):
            self.run_cases([dict(agenda(), meeting_date="2025-05-00")])

    def test_changed_retry_budget_does_not_rerun_completed_case(self):
        self.run_cases([agenda()], max_attempts=1)
        self.assertEqual(self.run_cases([agenda()], max_attempts=5)["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
