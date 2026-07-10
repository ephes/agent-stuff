import json
import os
import tempfile
import unittest
from pi_review_loop import result
from pi_review_loop.states import CLEAN, ISSUES


class TestReviewResult(unittest.TestCase):
    def test_scoped_clean_true_when_clean_with_skips(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="openai-codex/gpt-5.6-sol", cost=0.1,
            started_at=1.0, ended_at=2.0,
            skipped_files=[{"path": "big.json", "reason": "size", "size": 999999}],
            truncations=[], error=None, raw_verdict_line="REVIEW: CLEAN",
        )
        self.assertTrue(r.scoped_clean)

    def test_scoped_clean_false_when_clean_no_skips(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=None,
            started_at=1.0, ended_at=2.0, skipped_files=[], truncations=[],
            error=None, raw_verdict_line="REVIEW: CLEAN",
        )
        self.assertFalse(r.scoped_clean)

    def test_scoped_clean_false_when_issues(self):
        r = result.ReviewResult(
            state=ISSUES, items=[{"severity": "Warning", "path": "a", "message": "b"}],
            model="m", cost=None, started_at=1.0, ended_at=2.0,
            skipped_files=[{"path": "x"}], truncations=[], error=None,
            raw_verdict_line="REVIEW: ISSUES",
        )
        self.assertFalse(r.scoped_clean)

    def test_write_roundtrips_json(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=0.0, started_at=1.0,
            ended_at=2.0, skipped_files=[], truncations=[], error=None,
            raw_verdict_line=None,
        )
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "result.json")
            r.write(p)
            with open(p) as fh:
                data = json.load(fh)
        self.assertEqual(data["state"], CLEAN)
        self.assertEqual(data["scoped_clean"], False)
        self.assertEqual(data["duration_s"], 1.0)
        self.assertEqual(data["model"], "m")

    def test_write_serializes_scoped_clean_true(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=None, started_at=0.0,
            ended_at=1.5, skipped_files=[{"path": "big.json"}], truncations=[],
            error=None, raw_verdict_line="REVIEW: CLEAN",
        )
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "result.json")
            r.write(p)
            with open(p) as fh:
                data = json.load(fh)
        self.assertEqual(data["scoped_clean"], True)
        self.assertEqual(data["duration_s"], 1.5)


if __name__ == "__main__":
    unittest.main()
