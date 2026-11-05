import json
import tempfile
import unittest
from pathlib import Path

from nbim_flow.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]


class PolicyValidationTests(unittest.TestCase):
    def test_malformed_rule_id_is_rejected_before_retrieval(self):
        data = json.loads((ROOT / "policies/nbim_2025.json").read_text())
        data["rules"][0]["id"] = ["not-a-string"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_policy(path)

    def test_reversed_policy_period_is_rejected(self):
        data = json.loads((ROOT / "policies/nbim_2025.json").read_text())
        data["valid_from"], data["valid_through"] = data["valid_through"], data["valid_from"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_policy(path)


if __name__ == "__main__":
    unittest.main()
