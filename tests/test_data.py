import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nbim_flow.data import PREPROCESSING_VERSION, SAFE_FIELDS, normalize_vote, prepare_csv, safe_record, write_prepared


class PreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "input.csv"
        self.row = {
            "meeting_id": "meeting-1", "item_no": "1", "proposal_number": "1.1",
            "company_id": "0000123", "company": "Example ASA", "country": "Norway",
            "meeting_date": "2026-04-01", "proposal_text": "Elect Director Example",
            "mgmt_rec_raw": "For", "nbim_vote_raw": "Against", "nbim_vote": "MOT",
            "rationale_text": "Target-revealing explanation", "injection_flag": "0",
            "funds_disagree": "0",
        }

    def prepare(self, rows, source="real"):
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return prepare_csv(self.path, source)

    def test_unknown_and_nonvote_are_not_abstentions(self):
        for raw in ["One Year", "Three Years", "NONE", "Do Not Vote", "", None]:
            self.assertIsNone(normalize_vote(raw))
        self.assertEqual(normalize_vote(" withhold "), "MOT")
        self.assertEqual(normalize_vote("Avstå"), "AVSTÅ")
        self.assertEqual(normalize_vote("Against"), "MOT")

    def test_safe_payload_strips_labels_and_derived_values_are_recomputed(self):
        safe = safe_record({**self.row, "source": "real", "record_id": "forged",
                            "evidence_hash": "forged", "topic": "fake", "proposal_type": "answer"})
        self.assertEqual(set(safe), set(SAFE_FIELDS))
        self.assertNotIn("nbim_vote", safe)
        self.assertNotIn("rationale_text", safe)
        self.assertEqual(safe["company_id"], "0000123")
        self.assertEqual(safe["topic"], "board")
        self.assertNotEqual(safe["record_id"], "forged")
        self.assertEqual(safe_record({**safe, "nbim_vote": "FOR", "rationale_text": "leak"}), safe)

    def test_source_namespaces_and_content_fingerprints(self):
        first = safe_record({**self.row, "source": "real"})
        npx = safe_record({**self.row, "source": "npx"})
        changed = safe_record({**self.row, "source": "real", "proposal_text": "Updated proposal"})
        self.assertNotEqual(first["record_id"], npx["record_id"])
        self.assertEqual(first["record_id"], changed["record_id"])
        self.assertNotEqual(first["evidence_hash"], changed["evidence_hash"])
        no_leak = safe_record({**self.row, "source": "real", "nbim_vote_raw": "For"})
        self.assertEqual(first["evidence_hash"], no_leak["evidence_hash"])

    def test_exact_duplicates_are_removed(self):
        result = self.prepare([self.row, self.row.copy()])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["report"]["duplicate_rows"], 1)
        self.assertEqual(result["report"]["total_rows"], 2)
        self.assertFalse(result["quarantine"])

    def test_conflicting_labels_quarantine_entire_identity(self):
        conflict = {**self.row, "nbim_vote_raw": "For", "nbim_vote": "FOR"}
        result = self.prepare([self.row, conflict])
        self.assertFalse(result["records"])
        self.assertEqual(len(result["quarantine"]), 2)
        self.assertEqual(result["report"]["conflicting_ids"], 1)

    def test_missing_identity_text_and_invalid_calendar_date(self):
        rows = [
            {**self.row, "meeting_id": ""},
            {**self.row, "item_no": "2", "meeting_date": "2026-02-30"},
            {**self.row, "item_no": "3", "proposal_text": "   "},
        ]
        result = self.prepare(rows)
        self.assertFalse(result["records"])
        reasons = {reason for row in result["quarantine"] for reason in row["reasons"]}
        self.assertEqual(reasons, {"missing_identity", "invalid_meeting_date", "missing_proposal_text"})

    def test_proposal_number_fallback_and_unknown_label_preserved_for_inference(self):
        result = self.prepare([{**self.row, "item_no": "", "nbim_vote_raw": "Do Not Vote", "nbim_vote": ""}])
        self.assertEqual(result["records"][0]["item_no"], "1.1")
        self.assertIsNone(result["labels"][0]["vote_label"])
        self.assertFalse(result["labels"][0]["training_eligible"])

    def test_disagreement_and_source_quality_flags_are_outside_evidence(self):
        result = self.prepare([{**self.row, "funds_disagree": "1", "injection_flag": "1"}])
        self.assertFalse(result["labels"][0]["training_eligible"])
        self.assertIn("funds_disagree", result["labels"][0]["quality_flags"])
        self.assertNotIn("injection_flag", result["records"][0])

    def test_export_utf8_and_separate_labels(self):
        result = self.prepare([{**self.row, "nbim_vote_raw": "Abstain", "nbim_vote": "AVSTÅ"}])
        output = Path(self.temp.name) / "prepared"
        write_prepared(result, output)
        self.assertEqual(json.loads((output / "labels.jsonl").read_text())["vote_label"], "AVSTÅ")
        self.assertNotIn("nbim_vote", (output / "records.jsonl").read_text())
        self.assertEqual(json.loads((output / "report.json").read_text())["accepted_records"], 1)
        self.assertEqual(result["report"]["input_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(result["report"]["preprocessing_version"], PREPROCESSING_VERSION)

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare([self.row], "guessed")


if __name__ == "__main__":
    unittest.main()
