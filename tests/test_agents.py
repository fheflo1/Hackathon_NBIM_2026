import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nbim_flow.agents import LLMAgents, demo_propose
from nbim_flow.data import safe_record
from nbim_flow.policy import load_policy, retrieve

ROOT = Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    def test_separate_structured_calls_without_historical_answers(self):
        record = safe_record(dict(source="upload", meeting_id="m1", item_no="1",
                                  meeting_date="2025-06-01", proposal_text="Require an independent chair"))
        rules = retrieve(record, load_policy(ROOT / "policies/nbim_2025.json"))
        candidate = demo_propose(record, rules)
        outputs = [candidate, {"accepted": True, "retryable": False, "reason": "Underbygget av kildene"}]
        responses = [SimpleNamespace(id=f"response-{i}", status="completed", model="test-model", usage=None,
                                     output_text=json.dumps(output)) for i, output in enumerate(outputs)]
        with patch("openai.OpenAI") as client:
            client.return_value.responses.create.side_effect = responses
            agents = LLMAgents("author-version", "reviewer-version")
            proposed = agents.propose(dict(record, nbim_vote="MOT", rationale_text="LEAK_ME"), rules)
            reviewed = agents.review(record, rules, proposed)
            self.assertTrue(reviewed["accepted"])
            self.assertEqual(client.call_args.kwargs["max_retries"], 0)
            calls = client.return_value.responses.create.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual([c.kwargs["model"] for c in calls], ["author-version", "reviewer-version"])
            self.assertNotEqual(calls[0].kwargs["instructions"], calls[1].kwargs["instructions"])
            self.assertNotIn("LEAK_ME", calls[0].kwargs["input"])
            self.assertNotIn("nbim_vote", calls[0].kwargs["input"])
            self.assertNotIn("demo_patterns", calls[0].kwargs["input"])
            self.assertTrue(all(c.kwargs["text"]["format"]["strict"] for c in calls))
            self.assertTrue(all(c.kwargs["store"] is False for c in calls))

    def test_incomplete_response_is_failure_not_success(self):
        with patch("openai.OpenAI") as client:
            client.return_value.responses.create.return_value = SimpleNamespace(
                id="incomplete", status="incomplete", model="test-model", usage=None, output_text="")
            agents = LLMAgents("test-model")
            with self.assertRaises(ValueError):
                agents._call("test-model", "Instructions", {}, {}, "test")


if __name__ == "__main__":
    unittest.main()
