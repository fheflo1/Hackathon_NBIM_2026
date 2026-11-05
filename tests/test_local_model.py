import json
import unittest
from pathlib import Path

import httpx

from nbim_flow.agents import demo_propose
from nbim_flow.config import Settings
from nbim_flow.data import safe_record
from nbim_flow.local_model import OllamaAgents
from nbim_flow.policy import load_policy, retrieve

ROOT = Path(__file__).resolve().parents[1]


class LocalModelTests(unittest.TestCase):
    def test_native_schema_request_has_no_labels_and_normalized_usage(self):
        settings = Settings.from_env(
            ROOT, environ={"LLM_PROVIDER": "ollama", "LLM_MODEL": "test:7b"}
        )
        record = safe_record(
            dict(
                source="upload",
                meeting_id="m",
                item_no="1",
                meeting_date="2025-06-01",
                proposal_text="Require an independent chair",
            )
        )
        rules = retrieve(record, load_policy(ROOT / "policies/nbim_2025.json"))
        candidate = demo_propose(record, rules)
        requests = []

        def transport(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "done": True,
                    "done_reason": "stop",
                    "model": "test:7b",
                    "message": {"content": json.dumps(candidate)},
                    "prompt_eval_count": 111,
                    "eval_count": 42,
                },
            )

        agents = OllamaAgents(settings)
        agents.client.close()
        agents.client = httpx.Client(
            base_url=settings.base_url, transport=httpx.MockTransport(transport), trust_env=False
        )
        try:
            result = agents.propose(dict(record, nbim_vote="LEAK", rationale_text="LEAK"), rules)
            self.assertEqual(result, candidate)
            self.assertNotIn("LEAK", json.dumps(requests))
            self.assertEqual(requests[0]["format"]["type"], "object")
            self.assertFalse(requests[0]["stream"])
            self.assertEqual(agents.last_usage["usage"], {"input_tokens": 111, "output_tokens": 42})
        finally:
            agents.close()

    def test_incomplete_local_output_fails(self):
        agents = OllamaAgents(Settings.from_env(ROOT, environ={}))
        agents.client.close()
        agents.client = httpx.Client(
            base_url="http://localhost:11434",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"done": True, "done_reason": "length", "message": {"content": "{}"}}
                )
            ),
        )
        try:
            with self.assertRaises(ValueError):
                agents._call("test", "instructions", {}, {"type": "object"})
        finally:
            agents.close()


if __name__ == "__main__":
    unittest.main()
