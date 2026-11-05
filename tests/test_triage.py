"""Triage model and the triaged agenda flow (offline: no model server, fake agents)."""

import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from nbim_flow import triage
from nbim_flow.config import Settings

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/real_votes.csv"


@unittest.skipUnless(DATA.exists(), "needs data/real_votes.csv")
class TriageModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "triage.joblib"
        cls.report = triage.train(DATA, cls.path, last_train_year=2023)
        cls.model = triage.TriageModel.load(cls.path, DATA)
        raw = pd.read_csv(DATA, dtype=str, keep_default_na=False)
        r24 = raw[raw.year == "2024"]
        jp = r24[(r24.country == "Japan") & (r24.against_board == "1.0")].meeting_id.iloc[0]
        cls.meeting = r24[r24.meeting_id == jp]
        cls.records = [
            {"record_id": f"r{i}", "company": x.company, "meeting_date": x.meeting_date, "item_no": x.item_no,
             "proposal_text": x.proposal_text, "proponent": x.proponent,
             "mgmt_rec": {"For": "FOR", "Against": "MOT"}.get(x.mgmt_rec_raw, "")}
            for i, x in enumerate(cls.meeting.itertuples())
        ]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_validation_matches_the_documented_2024_numbers(self):
        v = self.report["validation"]
        self.assertEqual(v["year"], 2024)
        self.assertEqual((v["all"]["tp"], v["all"]["fp"], v["all"]["fn"]), (50, 29, 48))
        self.assertAlmostEqual(v["average_precision"], 0.5599, places=3)

    def test_future_labels_never_change_a_score(self):
        out = self.model.score(self.records)
        date = pd.Timestamp(self.meeting.meeting_date.iloc[0])
        hist = self.model.hist.copy()
        later = hist.meeting_date >= date
        hist.loc[later, "y"] = 1 - hist.loc[later, "y"]
        out2 = triage.TriageModel(self.model.b, hist).score(self.records)
        for key in out:
            self.assertEqual(out[key]["risk"], out2[key]["risk"])

    def test_names_are_masked_and_only_the_first_japanese_nominee_is_flagged(self):
        out = self.model.score(self.records)
        flagged = [r["record_id"] for r in self.records if out[r["record_id"]]["flagged"]]
        self.assertEqual(flagged, ["r0"])
        self.assertEqual(triage.mask_text("Elect Director Tanaka, Kunihiko", "Tanaka, Kunihiko"),
                         "Elect Director [PERSON]")
        self.assertTrue(all(out[k]["proposal_type"] == "DIRECTOR_ELECTION" for k in out))


class FakeTriage:
    """Flags record 'b'; everything else is low risk."""

    b = {"version": "fake", "thresholds": {"A": 0.5, "B": 0.5}, "catalogue": {"GVG 5.2": {"text": "Other business"}}}

    def score(self, records):
        return {r["record_id"]: {"model_version": "fake", "risk": 0.9 if r["item_no"] == "2" else 0.05,
                                 "lane": "A", "lane_label": "Sak uten person", "threshold": 0.5,
                                 "flagged": r["item_no"] == "2", "follow_board_vote": "FOR", "reasons": [],
                                 "protective": [], "precedent": [], "suggested_guideline": None, "facts": {}}
                for r in records}

    def card(self):
        return {"version": "fake"}


class TriagedFlowTests(unittest.TestCase):
    def setUp(self):
        from nbim_flow.web.service import AgendaService

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows keeps sqlite open briefly
        self.settings = Settings(root=Path(self.tmp.name), model="test:7b", light_workers=2,
                                 policy_file=str(ROOT / "policies/nbim_2025.json"))
        self.agent_calls, self.checks = [], []

        def reader(raw, filename, settings):
            recs = [{"record_id": f"x{i}", "item_no": str(i), "proposal_text": t, "company": "Acme",
                     "meeting_date": "2024-05-01", "mgmt_rec": "FOR", "evidence_hash": f"h{i}"}
                    for i, t in enumerate(["Approve Dividend", "Transact Other Business", "Elect Auditor",
                                           "Approve Financial Statements"], start=1)]
            return {"records": recs, "report": {}}, {}, {}

        def light(record, scores, catalogue):
            self.checks.append(record["item_no"])
            time.sleep(0.05)
            decision = "ESCALATE" if record["item_no"] == "4" else "FOLLOW_BOARD"
            return {"decision": decision, "guideline": "none", "reason": "ok", "confidence": 0.9, "failed": False}

        self.service = AgendaService(self.settings, reader=reader, identity=lambda: {}, triage=FakeTriage(),
                                     light_checker=light,
                                     note_writer=lambda r, s, c: {"guideline": "GVG 5.2", "justification": "x"})
        self.service._agent = self._fake_agent

    def tearDown(self):
        self.service.pool.shutdown(wait=True)
        self.service.close()
        self.tmp.cleanup()

    def _fake_agent(self, job_id, index, record, items, calls, counters):
        self.agent_calls.append(record["item_no"])
        items[index]["result"] = {"vote": "MOT", "status": "verified", "needs_human_review": False,
                                  "citations": [], "trace": []}
        counters["done"] += 1
        self.service.update(job_id, items=items, done=counters["done"])
        return calls + 2

    def test_flagged_first_low_risk_light_checked_doubt_escalated(self):
        job, _ = self.service.submit(b"x", "agenda.csv")
        for _ in range(200):
            job = self.service.get(job["id"])
            if job["status"] in ("completed", "needs_attention", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed", job.get("error"))
        self.assertEqual(self.agent_calls[0], "2")                 # flagged item first
        self.assertEqual(sorted(self.agent_calls), ["2", "4"])     # + the escalated one
        self.assertEqual(sorted(self.checks), ["1", "3", "4"])     # every low-risk item checked
        light = [i for i in job["items"] if (i.get("result") or {}).get("check") == "light"]
        self.assertEqual(sorted(i["item_no"] for i in light), ["1", "3"])
        self.assertTrue(all(i["result"]["vote"] == "FOR" for i in light))
        flagged = next(i for i in job["items"] if i["item_no"] == "2")
        self.assertEqual(flagged["model_note"]["guideline"], "GVG 5.2")

    def test_failed_light_check_is_never_treated_as_follow_board(self):
        self.service.light_checker = lambda r, s, c: {"decision": "FOLLOW_BOARD", "guideline": "none",
                                                      "reason": "", "confidence": 0.0, "failed": True}
        job, _ = self.service.submit(b"y", "agenda.csv")
        for _ in range(200):
            job = self.service.get(job["id"])
            if job["status"] in ("completed", "needs_attention", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(sorted(self.agent_calls), ["1", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
