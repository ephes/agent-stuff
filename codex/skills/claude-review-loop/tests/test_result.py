import json
import os
import tempfile
import unittest
from claude_review_loop import result
from claude_review_loop.states import CLEAN, ISSUES, SUGGESTIONS_ONLY


class TestReviewResult(unittest.TestCase):
    def test_scoped_clean_true_when_clean_with_skips(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="opus", cost=0.1,
            started_at=1.0, ended_at=2.0,
            skipped_files=[{"path": "big.json", "reason": "size", "size": 999999}],
            truncations=[], error=None,
        )
        self.assertTrue(r.scoped_clean)

    def test_scoped_clean_false_when_clean_no_skips(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=None,
            started_at=1.0, ended_at=2.0, skipped_files=[], truncations=[],
            error=None,
        )
        self.assertFalse(r.scoped_clean)

    def test_scoped_clean_false_when_issues(self):
        r = result.ReviewResult(
            state=ISSUES, items=[{"severity": "Warning", "path": "a", "message": "b"}],
            model="m", cost=None, started_at=1.0, ended_at=2.0,
            skipped_files=[{"path": "x"}], truncations=[], error=None,
        )
        self.assertFalse(r.scoped_clean)

    def test_scoped_clean_true_when_content_was_redacted(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=None,
            started_at=1.0, ended_at=2.0,
            redactions=[{"path": ".env", "section": "untracked file"}],
        )
        self.assertTrue(r.scoped_clean)

    def test_write_roundtrips_json(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=0.0, started_at=1.0,
            ended_at=2.0, skipped_files=[], truncations=[], error=None,
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
            error=None,
        )
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "result.json")
            r.write(p)
            with open(p) as fh:
                data = json.load(fh)
        self.assertEqual(data["scoped_clean"], True)
        self.assertEqual(data["duration_s"], 1.5)


class TestScoped(unittest.TestCase):
    def _result(self, state, **kw):
        return result.ReviewResult(state=state, items=[], model="m", cost=None,
                                   started_at=0.0, ended_at=1.0, **kw)

    def test_scoped_pass_covers_both_passing_states(self):
        for state in (CLEAN, SUGGESTIONS_ONLY):
            with self.subTest(state=state):
                self.assertTrue(self._result(
                    state, skipped_files=["big.bin"]).scoped_pass)
                self.assertFalse(self._result(state).scoped_pass)

    def test_scoped_pass_is_false_for_issues(self):
        self.assertFalse(self._result(ISSUES, truncations=["x"]).scoped_pass)

    def test_scoped_clean_stays_clean_only(self):
        self.assertFalse(self._result(
            SUGGESTIONS_ONLY, redactions=["x"]).scoped_clean)


if __name__ == "__main__":
    unittest.main()
