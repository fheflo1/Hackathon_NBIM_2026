"""The upload contract uses real LangGraph + SQLite, with fake model calls only."""

import csv
import io
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from nbim_flow.agents import demo_propose
from nbim_flow.config import Settings
from nbim_flow.web.api import create_app
from nbim_flow.web.ingestion import csv_agenda, date_value, read_agenda, validate_extraction
from nbim_flow.web.service import AgendaService
from nbim_flow.workflow import process_records

ROOT = Path(__file__).resolve().parents[1]
RAW = b"company,meeting_date,item_no,proposal_text\nTEST ASA,2025-06-01,1,Require an independent chair\n"


class Agents:
    def __init__(self):
        self.calls = 0

    def propose(self, record, rules, feedback=""):
        self.calls += 1
        return demo_propose(record, rules)

    def review(self, record, rules, candidate):
        self.calls += 1
        return {"accepted": True, "retryable": False, "reason": "Kildene og valget samsvarer."}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            root=Path(self.tmp.name),
            model="test:7b",
            reviewer_model="test:7b",
            policy_file=str(ROOT / "policies/nbim_2025.json"),
        )
        self.agents = Agents()

        def process(*args, **kwargs):
            return process_records(*args, **kwargs, agents=self.agents)

        self.service = AgendaService(
            self.settings, processor=process, identity=lambda: {"test:7b": "digest"}
        )
        self.client = TestClient(create_app(self.settings, self.service))

    def tearDown(self):
        self.service.pool.shutdown(wait=True)
        self.service.close()
        self.client.close()
        self.tmp.cleanup()

    def wait(self, job_id):
        for _ in range(300):
            response = self.client.get("/api/jobs/" + job_id)
            self.assertEqual(response.status_code, 200)
            job = response.json()
            if job["status"] in ("completed", "needs_attention", "failed"):
                return job
            time.sleep(0.01)
        self.fail("Upload worker did not finish")

    def upload(self, raw=RAW):
        response = self.client.post("/api/agenda", files={"file": ("agenda.csv", raw, "text/csv")})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_upload_automatically_runs_both_agents_and_exact_upload_is_reused(self):
        first = self.upload()
        job = self.wait(first["job"]["id"])
        self.assertEqual(job["status"], "completed", job)
        result = job["items"][0]["result"]
        self.assertEqual(
            (result["vote"], result["status"], self.agents.calls), ("FOR", "verified", 2)
        )
        self.assertTrue(result["citations"][0]["source_url"].startswith("https://www.nbim.no/"))
        self.assertTrue(result["trace"])
        proposals = [e for e in result["trace"] if e["event"] == "recommendation"]
        self.assertIn("Foreløpig: FOR", proposals[0]["detail"])
        second = self.upload()
        self.assertTrue(second["reused"])
        self.assertEqual(second["job"]["id"], job["id"])
        self.assertEqual(self.agents.calls, 2)
        with sqlite3.connect(self.settings.database_path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM web_job_events WHERE job_id=? AND event='upload_reused'",
                    (job["id"],),
                ).fetchone()[0],
                1,
            )
        output = self.client.get(f"/api/jobs/{job['id']}/export.csv")
        rows = list(csv.reader(io.StringIO(output.text.lstrip("\ufeff"))))
        self.assertEqual(rows[1][2], "FOR")
        self.assertEqual(output.headers["cache-control"], "no-store")
        self.assertNotIn("api_key", self.client.get("/api/jobs").text)

    def test_adding_one_point_reuses_the_unchanged_case(self):
        first = self.wait(self.upload()["job"]["id"])
        second_raw = RAW + b"TEST ASA,2025-06-01,2,Introduce voting caps\n"
        second = self.wait(self.upload(second_raw)["job"]["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual((second["done"], second["cached"]), (2, 1))
        self.assertEqual(self.agents.calls, 4)

    def test_policy_gap_is_manual_without_fake_confidence(self):
        job = self.wait(self.upload(RAW.replace(b"2025-06-01", b"2026-06-01"))["job"]["id"])
        self.assertEqual(job["status"], "needs_attention")
        r = job["items"][0]["result"]
        self.assertEqual((r["vote"], r["confidence"], r["citations"]), ("AVSTÅ", None, []))
        self.assertTrue(r["needs_human_review"])
        self.assertEqual(self.agents.calls, 0)

    def test_invalid_agenda_has_no_partial_votes_and_can_be_reuploaded(self):
        bad = RAW + b"TEST ASA,2025-06-01,2,\n"
        first = self.wait(self.upload(bad)["job"]["id"])
        self.assertEqual(first["status"], "failed")
        self.assertIn("tomme", first["error"])
        self.assertEqual(self.agents.calls, 0)
        second = self.upload(bad)
        self.assertFalse(second["reused"])
        self.wait(second["job"]["id"])

    def test_persistence_across_restart_reuses_without_model_calls(self):
        job = self.wait(self.upload()["job"]["id"])
        self.service.close()
        service = AgendaService(self.settings, identity=lambda: {"test:7b": "digest"})
        try:
            reused, cached = service.submit(RAW, "nytt-navn.csv")
            self.assertTrue(cached)
            self.assertEqual(reused["id"], job["id"])
        finally:
            service.close()

    def test_browser_boundary_rejects_external_origins_and_invalid_files(self):
        response = self.client.post(
            "/api/agenda",
            headers={"Origin": "https://evil.example"},
            files={"file": ("agenda.csv", RAW)},
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/agenda", files={"file": ("agenda.exe", RAW)})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/jobs/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/no-such-endpoint").status_code, 404)
        self.assertEqual(
            self.client.get("/api/health", headers={"Host": "evil.example"}).status_code, 400
        )

    def test_model_outage_has_safe_error_not_stacktrace(self):
        with patch.object(
            self.service, "identity", side_effect=ConnectionError("secret-model-connection")
        ):
            response = self.client.post("/api/agenda", files={"file": ("agenda.csv", RAW)})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-model-connection", response.text)

    def test_renamed_models_invalidate_upload_cache(self):
        first = self.wait(self.upload()["job"]["id"])
        with patch.object(self.service, "identity", return_value={"test:7b": "changed-digest"}):
            second = self.upload()
        self.assertFalse(second["reused"])
        self.assertNotEqual(second["job"]["id"], first["id"])
        self.wait(second["job"]["id"])


class IngestionTests(unittest.TestCase):
    def test_norwegian_csv_normalizes_dates_and_keeps_labels_away_from_evidence(self):
        raw = "selskap;møtedato;saksnummer;sak;nbim_vote;rationale_text\nTEST ASA;01.06.2025;1;Require an independent chair;MOT;SECRET\n".encode(
            "utf-8-sig"
        )
        prepared, refs, meta = csv_agenda(raw)
        record = prepared["records"][0]
        self.assertEqual(record["meeting_date"], "2025-06-01")
        self.assertNotIn("rationale_text", record)
        self.assertNotIn("nbim_vote", record)
        self.assertEqual(meta["extraction_calls"], 0)

    def test_missing_dates_or_conflicting_points_cannot_be_guessed(self):
        with self.assertRaises(ValueError):
            csv_agenda(RAW.replace(b"2025-06-01", b""))
        with self.assertRaises(ValueError):
            csv_agenda(RAW + b"TEST ASA,2025-06-01,1,Introduce voting caps\n")
        self.assertEqual(date_value("June 1, 2025"), "2025-06-01")
        self.assertEqual(date_value("1. juni 2025"), "2025-06-01")

    def test_document_output_must_match_original_page_and_date(self):
        pages = ["TEST ASA Annual General Meeting June 1, 2025. 1. Require an independent chair."]
        extraction = {
            "company": "TEST ASA",
            "company_evidence": "TEST ASA",
            "meeting_date": "2025-06-01",
            "meeting_date_evidence": "June 1, 2025",
            "items": [{"item_no": "1", "source_quote": "Require an independent chair.", "page": 1}],
        }
        prepared, refs = validate_extraction(extraction, pages)
        self.assertEqual(refs[prepared["records"][0]["record_id"]]["page"], 1)
        for modified in [
            dict(extraction, meeting_date="2026-06-01"),
            dict(extraction, company="Invented Inc"),
            dict(
                extraction,
                items=[{"item_no": "1", "source_quote": "An invented proposal.", "page": 1}],
            ),
            dict(
                extraction,
                items=[
                    {"item_no": "1", "source_quote": "Require an independent chair.", "page": 2}
                ],
            ),
        ]:
            with self.assertRaises(ValueError):
                validate_extraction(modified, pages)

    def test_text_document_runs_source_bound_extraction_before_voting(self):
        from unittest.mock import Mock

        pages = "TEST ASA General meeting June 1, 2025. Require an independent chair."
        extraction = {
            "company": "TEST ASA",
            "company_evidence": "TEST ASA",
            "meeting_date": "2025-06-01",
            "meeting_date_evidence": "June 1, 2025",
            "items": [{"item_no": "1", "source_quote": "Require an independent chair.", "page": 1}],
        }
        provider = Mock()
        provider._call.return_value = extraction
        provider.last_usage = {"usage": {"input_tokens": 100, "output_tokens": 40}}
        with patch("nbim_flow.web.ingestion.create_agents", return_value=provider):
            result, refs, metadata = read_agenda(
                pages.encode(), "agenda.txt", Settings(root=ROOT, model="test:7b")
            )
        self.assertEqual(metadata["extraction_calls"], 1)
        self.assertEqual(result["records"][0]["proposal_text"], "Require an independent chair.")
        self.assertEqual(list(refs.values())[0]["page"], 1)
        provider.close.assert_called_once()

    def test_empty_encrypted_and_invalid_pdf_never_trigger_a_model_call(self):
        from pypdf import PdfWriter

        for encrypted in (False, True):
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            if encrypted:
                writer.encrypt("test-password")
            buffer = io.BytesIO()
            writer.write(buffer)
            with patch("nbim_flow.web.ingestion.create_agents") as create:
                with self.assertRaises(ValueError):
                    read_agenda(buffer.getvalue(), "agenda.pdf", Settings(root=ROOT))
                create.assert_not_called()
        with self.assertRaises(ValueError):
            read_agenda(b"not a PDF", "broken.pdf", Settings(root=ROOT))

    def test_long_text_is_rejected_without_silent_truncation_or_model_calls(self):
        with patch("nbim_flow.web.ingestion.create_agents") as create:
            with self.assertRaises(ValueError):
                read_agenda(b"x" * 24001, "agenda.txt", Settings(root=ROOT))
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
