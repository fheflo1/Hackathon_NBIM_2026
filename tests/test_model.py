"""Regression checks for temporal leakage, target leakage and queue retention."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from nbim_flow.model import chronological_split, select_routing_threshold


def fixture():
    records, labels = [], []
    for year in (2023, 2024, 2025):
        for index, vote in enumerate(("FOR", "FOR", "MOT", "AVSTÅ")):
            record_id = f"{year}-{index}"
            text = {
                "FOR": "Approve routine annual accounts",
                "MOT": "Elect executive combined chair",
                "AVSTÅ": "Review unavailable proposal details",
            }[vote]
            records.append(
                {
                    "record_id": record_id,
                    "source": "real",
                    "meeting_date": f"{year}-05-0{index + 1}",
                    "proposal_text": text,
                    "mgmt_rec": "FOR" if index != 2 else "MOT",
                    # These must never appear in the fitted vocabulary.
                    "rationale_text": "leakysecret",
                    "nbim_vote": "leakysecret",
                }
            )
            labels.append({"record_id": record_id, "vote_label": vote, "training_eligible": True})
    return records, labels


class TemporalSplitTests(unittest.TestCase):
    def test_year_split_keeps_newest_year_unseen(self):
        records, labels = fixture()
        enriched = [{**r, "vote_label": label["vote_label"]} for r, label in zip(records, labels)]
        split = chronological_split(enriched)
        self.assertEqual(split["metadata"]["train"]["date_max"][:4], "2023")
        self.assertEqual(split["metadata"]["validation"]["date_min"][:4], "2024")
        self.assertEqual(split["metadata"]["test"]["date_min"][:4], "2025")

    def test_fallback_groups_same_day(self):
        records = [
            {"record_id": f"{day}-{i}", "meeting_date": f"2025-05-{day:02d}", "vote_label": "MOT"}
            for day in range(1, 7)
            for i in range(2)
        ]
        split = chronological_split(records)
        date_sets = [
            {r["meeting_date"] for r in split[name]} for name in ("train", "validation", "test")
        ]
        self.assertFalse(date_sets[0] & date_sets[1])
        self.assertFalse(date_sets[1] & date_sets[2])
        self.assertLess(max(date_sets[0]), min(date_sets[1]))
        self.assertLess(max(date_sets[1]), min(date_sets[2]))

    def test_not_enough_dates_fails(self):
        with self.assertRaises(ValueError):
            chronological_split(
                [{"record_id": "a", "meeting_date": "2025-05-01", "vote_label": "MOT"}]
            )

    def test_threshold_uses_positives_and_ties(self):
        selection = select_routing_threshold(
            ["MOT", "MOT", "MOT", "FOR"], [0.2, 0.5, 0.5, 0.8], 2 / 3
        )
        self.assertEqual(selection["threshold"], 0.5)
        self.assertAlmostEqual(selection["validation_recall"], 2 / 3)
        self.assertAlmostEqual(selection["validation_precision"], 2 / 3)

    def test_no_validation_mot_routes_all_explicitly(self):
        selection = select_routing_threshold(["FOR", "FOR"], [0.1, 0.8])
        self.assertEqual(selection["threshold"], 0)
        self.assertIsNone(selection["validation_recall"])


@unittest.skipUnless(importlib.util.find_spec("sklearn"), "scikit-learn not installed")
class ModelTests(unittest.TestCase):
    def test_text_only_fit_and_test_vocabulary_excluded(self):
        from nbim_flow.model import load_model, train_model

        records, labels = fixture()
        records[-1]["proposal_text"] += " holdoutsecret"
        with tempfile.TemporaryDirectory() as directory:
            report = train_model(records, labels, directory)
            bundle = load_model(directory)
            vocabulary = bundle["vectorizer"].vocabulary_
            self.assertNotIn("leakysecret", vocabulary)
            self.assertNotIn("holdoutsecret", vocabulary)
            self.assertEqual(report["features"], ["proposal_text"])
            self.assertEqual(report["test"]["model"]["count"], 4)
            self.assertEqual(report["test"]["board_baseline"]["count"], 4)
            self.assertTrue((Path(directory) / "test_predictions.csv").is_file())

    def test_priority_preserves_every_record_and_model_ignores_labels(self):
        from nbim_flow.model import prioritize, train_model

        records, labels = fixture()
        with tempfile.TemporaryDirectory() as directory:
            train_model(records, labels, directory)
            first = prioritize(records, directory)
            changed = [
                {**r, "nbim_vote": "MOT", "rationale_text": "vocabulary attack"} for r in records
            ]
            second = prioritize(changed, directory)
            self.assertEqual([r["record_id"] for r in first], [r["record_id"] for r in records])
            self.assertEqual([r["p_mot"] for r in first], [r["p_mot"] for r in second])
            self.assertTrue(all(r["priority"] in ("high", "normal") for r in first))

    def test_mixed_sources_rejected(self):
        from nbim_flow.model import train_model

        records, labels = fixture()
        records[-1]["source"] = "npx"
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            train_model(records, labels, directory)

    def test_unknown_and_ineligible_labels_excluded(self):
        from nbim_flow.model import train_model

        records, labels = fixture()
        labels[0]["training_eligible"] = False
        labels[1]["vote_label"] = None
        with tempfile.TemporaryDirectory() as directory:
            report = train_model(records, labels, directory)
            self.assertEqual(report["excluded"], {"training_ineligible": 1, "unknown_label": 1})
            self.assertEqual(report["split"]["train"]["count"], 2)

    def test_cluster_topics_are_optional(self):
        from nbim_flow.model import prioritize, train_model

        records, labels = fixture()
        with tempfile.TemporaryDirectory() as directory:
            report = train_model(records, labels, directory, clusters=2)
            self.assertEqual(len(report["cluster_topics"]), 2)
            self.assertTrue(all("cluster" in row for row in prioritize(records, directory)))


if __name__ == "__main__":
    unittest.main()
