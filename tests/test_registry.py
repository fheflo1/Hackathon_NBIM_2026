import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_model import fixture

from nbim_flow.model import load_model, train_model
from nbim_flow.registry import (
    activate_run,
    adopt_legacy_model,
    list_runs,
    read_report,
    resolve_model,
)


class RegistryTests(unittest.TestCase):
    def test_adopting_existing_model_preserves_weights(self):
        records, labels = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            train_model(records, labels, tmp)
            root = Path(tmp)
            before = hashlib.sha256((root / "model.joblib").read_bytes()).hexdigest()
            (root / "active.json").unlink()
            run_id = adopt_legacy_model(root)
            self.assertTrue(run_id.endswith("-legacy"))
            self.assertEqual(hashlib.sha256(resolve_model(root).read_bytes()).hexdigest(), before)

    def test_model_versions_preserved_and_rollback_restores_prior_run(self):
        records, labels = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            first = train_model(records, labels, tmp, target_recall=0.8)
            old = list_runs(tmp)[0]["run_id"]
            train_model(records, labels, tmp, target_recall=1.0)
            self.assertEqual(len(list_runs(tmp)), 2)
            self.assertNotEqual(read_report(tmp)["model_id"], first["model_id"])
            activate_run(tmp, old)
            self.assertEqual(read_report(tmp)["model_id"], first["model_id"])
            self.assertEqual(load_model(tmp)["model_id"], first["model_id"])

    def test_corruption_rejected_before_pickle_loading(self):
        records, labels = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            train_model(records, labels, tmp)
            location = resolve_model(tmp)
            location.write_bytes(b"broken")
            with patch("joblib.load") as load:
                with self.assertRaises(ValueError):
                    load_model(tmp)
                load.assert_not_called()

    def test_legacy_output_is_archived_on_first_new_training(self):
        records, labels = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("model.joblib", "report.json", "test_predictions.csv"):
                (root / name).write_text("legacy bytes")
            train_model(records, labels, tmp)
            archived = [r for r in list_runs(tmp) if r["metadata"].get("legacy")]
            self.assertEqual(len(archived), 1)
            self.assertEqual(
                (root / "runs" / archived[0]["run_id"] / "model.joblib").read_text(), "legacy bytes"
            )


if __name__ == "__main__":
    unittest.main()
