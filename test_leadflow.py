"""Unit tests for LeadFlow. Run: python -m unittest -v test_leadflow.py"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import leadflow


class LeadFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.outbox_path = Path(self.temp.name) / "outbox.jsonl"
        self.db_patch = patch.object(leadflow, "DB_PATH", self.db_path)
        self.outbox_patch = patch.object(leadflow, "OUTBOX_PATH", self.outbox_path)
        self.db_patch.start()
        self.outbox_patch.start()
        self.conn = leadflow.connect_db()

    def tearDown(self):
        self.conn.close()
        self.db_patch.stop()
        self.outbox_patch.stop()
        self.temp.cleanup()

    def test_valid_email_lead(self):
        lead = {"name":"Asha","requirement":"Need a chatbot","email":"asha@example.com"}
        self.assertEqual(leadflow.validate_lead(lead), [])

    def test_reject_missing_name(self):
        lead = {"name":"","requirement":"Need a chatbot","email":"asha@example.com"}
        self.assertIn("name is required", leadflow.validate_lead(lead))

    def test_reject_missing_requirement(self):
        lead = {"name":"Asha","requirement":"","email":"asha@example.com"}
        self.assertIn("requirement is required", leadflow.validate_lead(lead))

    def test_reject_invalid_contact(self):
        lead = {"name":"Asha","requirement":"Need a chatbot","email":"not-an-email","phone":"123"}
        self.assertIn("provide at least one valid email or phone", leadflow.validate_lead(lead))

    def test_score_and_hot_threshold(self):
        lead = {"name":"Ananya Rao","requirement":"Need to implement AI automation urgently",
                "email":"ananya@example.com","phone":"+91 98765 43210","company":"Aster Health",
                "budget_inr":100000,"industry":"healthcare","source":"referral"}
        score, priority, reasons = leadflow.score_lead(lead)
        self.assertEqual(score, 85)
        self.assertEqual(priority, "Hot")
        self.assertTrue(reasons)

    def test_cold_lead(self):
        lead = {"name":"Kiran","requirement":"Just browsing","email":"kiran@example.com","source":"unknown"}
        score, priority, _ = leadflow.score_lead(lead)
        self.assertEqual(priority, "Cold")
        self.assertLess(score, 40)

    def test_fallback_has_required_fields(self):
        result = leadflow.fallback_content({"name":"Asha","requirement":"customer support chatbot"})
        self.assertTrue(result["pain_point"])
        self.assertEqual(result["recommended_service"], "Customer Support Chatbot")
        self.assertTrue(result["follow_up"])

    def test_duplicate_by_email(self):
        lead = {"name":"Asha","requirement":"Need a chatbot","email":"asha@example.com","company":"ABC"}
        leadflow.process_one(self.conn, lead)
        result = leadflow.process_one(self.conn, {**lead, "name":"Asha Duplicate","email":" ASHA@example.com "})
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM leads WHERE status='qualified'").fetchone()[0], 1)

    def test_duplicate_by_phone_and_company(self):
        lead = {"name":"Asha","requirement":"Need a chatbot","phone":"+91 98765 43210","company":"ABC"}
        leadflow.process_one(self.conn, lead)
        result = leadflow.process_one(self.conn, {**lead, "name":"Asha New"})
        self.assertEqual(result["status"], "duplicate")

    def test_invalid_lead_is_stored_as_rejected(self):
        result = leadflow.process_one(self.conn, {"name":"","requirement":"", "email":"bad"})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.conn.execute("SELECT status FROM leads").fetchone()[0], "rejected")

    def test_hot_lead_creates_one_alert(self):
        lead = {"name":"Ananya Rao","requirement":"Need to implement AI automation urgently",
                "email":"ananya@example.com","phone":"+91 98765 43210","company":"Aster Health",
                "budget_inr":100000,"industry":"healthcare","source":"referral"}
        with patch.dict("os.environ", {}, clear=True):
            leadflow.process_one(self.conn, lead)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 1)
        self.assertTrue(self.outbox_path.exists())

    def test_inspectable_event_history(self):
        leadflow.process_one(self.conn, {"name":"Asha","requirement":"Need a chatbot","email":"asha@example.com"})
        count = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
