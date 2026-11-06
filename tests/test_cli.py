import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nbim_flow.cli import main
from nbim_flow.config import Settings

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "data/agenda.csv").write_bytes(
            (ROOT / "tests/fixtures/agenda.csv").read_bytes()
        )
        self.settings = Settings(
            root=self.root, model="test-local:7b", policy_file=str(ROOT / "policies/nbim_2025.json")
        )

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, args):
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch("nbim_flow.cli.Settings.from_env", return_value=self.settings),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_offline_doctor_and_demo_process_evaluation_backup(self):
        self.assertEqual(self.call(["doctor"])[0], 0)
        args = [
            "process",
            "--source",
            "upload",
            "--input",
            "data/agenda.csv",
            "--mode",
            "demo",
        ]
        code, report = self.call(args)
        self.assertEqual((code, report["processed"]), (0, 4))
        self.assertEqual(self.call(args)[1]["skipped"], 4)
        code, evaluation = self.call(
            ["evaluate", "--source", "upload", "--input", "data/agenda.csv", "--mode", "demo"]
        )
        self.assertEqual(
            (code, evaluation["processed_count"], evaluation["known_label_evaluated_count"]),
            (0, 4, 0),
        )
        backup = self.root / "backup.sqlite"
        self.assertEqual(self.call(["backup", "--out", str(backup)])[0], 0)
        self.assertTrue(backup.exists())
        self.assertEqual(self.call(["status", "--mode", "demo"])[1]["current_case_count"], 4)

    def test_probe_failure_has_nonzero_exit_code(self):
        with patch(
            "nbim_flow.diagnostics.probe",
            return_value={"connected": False, "structured_outputs_ok": False},
        ):
            self.assertEqual(self.call(["probe"])[0], 1)

    def test_models_lists_local_metadata_without_generation(self):
        with patch(
            "nbim_flow.local_model.local_models",
            return_value=[{"name": "test:7b", "digest": "abc"}],
        ):
            self.assertEqual(self.call(["models"])[1][0]["name"], "test:7b")

    def test_process_failure_has_nonzero_exit_code(self):
        with patch(
            "nbim_flow.workflow.process_records",
            return_value={"errors": 1, "stopped_reason": "authentication"},
        ):
            self.assertEqual(
                self.call(["process", "--source", "upload", "--input", "data/agenda.csv"])[0],
                2,
            )

    def test_missing_upload_path_exits_with_actionable_message(self):
        with self.assertRaises(SystemExit) as result:
            self.call(["process", "--source", "upload"])
        self.assertEqual(result.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
