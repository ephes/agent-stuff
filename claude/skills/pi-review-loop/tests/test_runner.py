import os
import sys
import tempfile
import unittest
from pi_review_loop import runner
from pi_review_loop.states import CLEAN, ISSUES, CRASHED, STALLED, PROVIDER_ERROR

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_pi.py")]


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, mode, **kw):
        defaults = dict(stall_timeout=2, retry_grace=1, global_deadline=30,
                        poll_interval=0.05, model="fake/model")
        defaults.update(kw)
        return runner.run_review(cmd=FAKE + [mode], run_dir=self.run_dir, **defaults)

    def test_clean(self):
        r = self._run("clean")
        self.assertEqual(r.state, CLEAN)
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "result.json")))
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "events.jsonl")))

    def test_issues_items_parsed(self):
        r = self._run("issues")
        self.assertEqual(r.state, ISSUES)
        self.assertEqual(r.items[0]["severity"], "Warning")

    def test_hang_is_stalled_and_killed(self):
        r = self._run("hang", stall_timeout=1)
        self.assertEqual(r.state, STALLED)

    def test_crash_with_malformed_output(self):
        r = self._run("crash")
        self.assertEqual(r.state, CRASHED)
        import json
        with open(os.path.join(self.run_dir, "events.jsonl")) as fh:
            for line in fh:
                json.loads(line)  # must not raise

    def test_posthang_returns_clean_without_waiting(self):
        # M3: verdict present, process won't exit -> must finish CLEAN promptly.
        r = self._run("posthang", global_deadline=30)
        self.assertEqual(r.state, CLEAN)

    def test_provider_error(self):
        from pi_review_loop.states import PROVIDER_ERROR
        r = self._run("provider_error")
        self.assertEqual(r.state, PROVIDER_ERROR)
        self.assertIn("529", r.error or "")


if __name__ == "__main__":
    unittest.main()
