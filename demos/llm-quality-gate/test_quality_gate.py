import json
import tempfile
import unittest
from pathlib import Path

from quality_gate import evaluate_record, main, read_jsonl


class QualityGateTests(unittest.TestCase):
    def test_passes_complete_record(self):
        result = evaluate_record(
            {
                "case_id": "complete",
                "response": "The order ships tomorrow. Source: order record.",
                "required_terms": ["ships tomorrow"],
                "required_evidence": ["order record"],
                "must_have_citation": True,
                "citations": ["order-123"],
            }
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["failures"], [])

    def test_reports_missing_required_term(self):
        result = evaluate_record(
            {
                "case_id": "missing",
                "response": "The order is being prepared.",
                "required_terms": ["ships tomorrow"],
            }
        )
        self.assertFalse(result["passed"])
        self.assertIn("required_terms", result["failures"])

    def test_rejects_forbidden_claim(self):
        result = evaluate_record(
            {
                "case_id": "claim",
                "response": "This is guaranteed to arrive today.",
                "forbidden_terms": ["guaranteed"],
            }
        )
        self.assertFalse(result["passed"])
        self.assertIn("forbidden_terms_absent", result["failures"])

    def test_checks_citation_requirement(self):
        result = evaluate_record(
            {
                "case_id": "citation",
                "response": "The answer is based on the supplied record.",
                "must_have_citation": True,
            }
        )
        self.assertFalse(result["checks"]["citations_present"])

    def test_rejects_overlong_response(self):
        result = evaluate_record(
            {"case_id": "length", "response": "12345", "max_chars": 4}
        )
        self.assertFalse(result["checks"]["maximum_length"])

    def test_jsonl_and_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text(
                json.dumps({"case_id": "ok", "response": "Ready"}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(len(read_jsonl(path)), 1)
            self.assertEqual(main([str(path)]), 0)


if __name__ == "__main__":
    unittest.main()
