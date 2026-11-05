import unittest

from nbim_flow.data import safe_record
from nbim_flow.evaluation import evaluate_results


class StoredEvaluationTests(unittest.TestCase):
    def record(self, item, source="real", **extra):
        return safe_record(
            {
                "source": source,
                "meeting_id": "m",
                "item_no": str(item),
                "proposal_text": "Elect Director",
                "meeting_date": "2025-06-01",
                "mgmt_rec": "FOR",
                **extra,
            }
        )

    def result(self, record, vote="FOR", **extra):
        return {
            **record,
            "vote": vote,
            "mode": "llm",
            "status": "verified",
            "needs_human_review": False,
            "fallback_type": None,
            "updated_at": "2026-01-01T12:00:00+00:00",
            **extra,
        }

    def label(self, record, vote):
        return {"record_id": record["record_id"], "vote_label": vote}

    def test_unknown_labels_are_not_negative_examples_and_coverage_is_explicit(self):
        records = [self.record(i) for i in range(4)]
        labels = [
            self.label(records[0], "MOT"),
            self.label(records[1], None),
            self.label(records[3], "FOR"),
        ]
        results = [
            self.result(records[0], "MOT"),
            self.result(records[1], "MOT"),
            self.result(records[2], "FOR"),
        ]
        report = evaluate_results(records, labels, results)
        self.assertEqual(report["available_input_count"], 4)
        self.assertEqual(report["processed_count"], 3)
        self.assertEqual(report["known_label_evaluated_count"], 1)
        self.assertEqual(report["unknown_label_processed_count"], 2)
        self.assertEqual(report["coverage"], 0.75)
        self.assertEqual(report["known_label_coverage"], 0.5)
        self.assertEqual(report["metrics"]["mot_confusion"], {"tp": 1, "fp": 0, "fn": 0, "tn": 0})

    def test_latest_current_evidence_and_mode_are_matched(self):
        record = self.record(1)
        stale = self.record(1, proposal_text="Different earlier proposal")
        results = [
            self.result(record, "MOT", updated_at="2026-01-02T12:00:00Z", run_key="new"),
            self.result(record, "FOR", updated_at="2026-01-01T12:00:00Z", run_key="old"),
            self.result(stale, "FOR", updated_at="2026-02-01T12:00:00Z"),
            self.result(
                record, "FOR", mode="demo", status="demo_checked", updated_at="2026-03-01T12:00:00Z"
            ),
        ]
        report = evaluate_results([record], [self.label(record, "MOT")], results)
        self.assertEqual(report["metrics"]["mot_recall"], 1.0)
        demo = evaluate_results([record], [self.label(record, "MOT")], results, mode="demo")
        self.assertEqual(demo["evaluation_kind"], "deterministic_demo_only")
        self.assertEqual(demo["verified_count"], 0)
        self.assertEqual(demo["demo_checked_count"], 1)
        self.assertEqual(demo["metrics"]["mot_recall"], 0.0)

    def test_sources_are_not_joined_on_meeting_and_item(self):
        real = self.record(1)
        npx = self.record(1, source="npx")
        report = evaluate_results(
            [real], [self.label(real, "MOT"), self.label(npx, "FOR")], [self.result(npx)]
        )
        self.assertEqual(report["processed_count"], 0)
        self.assertEqual(report["known_label_evaluated_count"], 0)

    def test_board_cohort_is_comparable_and_fallbacks_remain_visible(self):
        first, second, third = self.record(1), self.record(2), self.record(3, mgmt_rec="None")
        records = [first, second, third]
        labels = [self.label(first, "MOT"), self.label(second, "FOR"), self.label(third, "AVSTÅ")]
        results = [
            self.result(first, "MOT"),
            self.result(second, "MOT"),
            self.result(
                third,
                "AVSTÅ",
                status="human_review",
                needs_human_review=True,
                fallback_type="insufficient_evidence",
            ),
        ]
        report = evaluate_results(records, labels, results)
        self.assertEqual(report["metrics"]["mot_precision"], 0.5)
        self.assertEqual(report["metrics"]["mot_recall"], 1.0)
        self.assertAlmostEqual(report["metrics"]["mot_f1"], 2 / 3)
        self.assertEqual(report["board_baseline"]["count"], 2)
        self.assertEqual(report["agent_on_board_available_subset"]["count"], 2)
        self.assertEqual(report["board_missing_count"], 1)
        self.assertEqual(report["fallback_abstentions"], 1)
        self.assertEqual(report["needs_human_count"], 1)
        self.assertEqual(report["verified_count"], 2)
        self.assertEqual(
            report["metrics"]["confusion_matrix"]["rows_actual_columns_predicted"],
            [[0, 1, 0], [0, 1, 0], [0, 0, 1]],
        )

    def test_processing_is_pending_even_if_older_result_was_finished(self):
        record = self.record(1)
        results = [
            self.result(record, "MOT"),
            self.result(record, status="processing", updated_at="2026-02-01T00:00:00Z"),
        ]
        report = evaluate_results([record], [self.label(record, "MOT")], results)
        self.assertEqual(report["processed_count"], 0)
        self.assertEqual(report["pending_count"], 1)
        self.assertIsNone(report["metrics"]["mot_recall"])

    def test_timestamp_offsets_are_compared_as_times(self):
        record = self.record(1)
        results = [
            self.result(record, "MOT", updated_at="2026-01-01T11:00:00+00:00"),
            self.result(record, "FOR", updated_at="2026-01-01T12:00:00+02:00"),
        ]
        report = evaluate_results([record], [self.label(record, "MOT")], results)
        self.assertEqual(report["metrics"]["mot_recall"], 1.0)

    def test_empty_cohort_and_conflicting_labels(self):
        report = evaluate_results([], [], [])
        self.assertEqual(report["coverage"], 0.0)
        self.assertIsNone(report["metrics"]["accuracy"])
        record = self.record(1)
        with self.assertRaises(ValueError):
            evaluate_results([record], [self.label(record, "MOT"), self.label(record, "FOR")], [])

    def test_mixed_configurations_are_reported_and_verified_coverage_is_explicit(self):
        first, second = self.record(1), self.record(2)
        report = evaluate_results(
            [first, second],
            [self.label(first, "FOR"), self.label(second, "FOR")],
            [
                self.result(first, config={"model": "a", "prompt_version": "v1"}),
                self.result(
                    second,
                    status="human_review",
                    needs_human_review=True,
                    config={"model": "b", "prompt_version": "v2"},
                ),
            ],
        )
        self.assertEqual(report["configuration_count"], 2)
        self.assertTrue(report["mixed_configuration_warning"])
        self.assertEqual(sum(c["processed_count"] for c in report["configuration_summaries"]), 2)
        self.assertEqual(report["verified_coverage"], 0.5)
        self.assertEqual(report["verified_known_label_coverage"], 0.5)


if __name__ == "__main__":
    unittest.main()
