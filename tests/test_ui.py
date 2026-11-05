import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "NBIM_ROOT": str(ROOT),
                "NBIM_DATABASE_PATH": str(Path(self.tmp.name) / "audit.sqlite"),
                "LLM_PROVIDER": "ollama",
                "LLM_MODEL": "test-local:7b",
                "NBIM_LOG_LEVEL": "ERROR",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def app(self):
        return AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)

    def test_setup_and_every_page_render_without_model_calls(self):
        app = self.app()
        self.assertFalse(app.exception)
        for name in ["Data", "Prioriteringsmodell", "Drift", "Workflow", "Manuell oppfølging"]:
            app.sidebar.radio[0].set_value(name).run(timeout=30)
            self.assertFalse(app.exception, name)
            self.assertFalse(app.error, name)

    def test_demo_processing_and_cache(self):
        app = self.app()
        app.sidebar.radio[0].set_value("Saksbehandling").run(timeout=30)
        app.button[0].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.session_state["last_batch"]["processed"], 4)
        app.button[0].click().run(timeout=30)
        self.assertEqual(app.session_state["last_batch"]["skipped"], 4)
        self.assertEqual(app.session_state["last_batch"]["api_calls"], 0)


if __name__ == "__main__":
    unittest.main()
