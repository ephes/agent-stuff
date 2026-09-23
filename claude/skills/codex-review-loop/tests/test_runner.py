import json
import os
import signal
import sys
import tempfile
import unittest
from unittest import mock

from codex_review_loop import runner
from tests.helpers import FAKE


class TestExitAcceptance(unittest.TestCase):
    TERM, KILL = int(signal.SIGTERM), int(signal.SIGKILL)

    def test_clean_exit_is_always_acceptable(self):
        self.assertTrue(runner.exit_is_acceptable(0, delivered_signals=set()))
        self.assertTrue(runner.exit_is_acceptable(0, delivered_signals={self.TERM}))

    def test_a_death_by_a_delivered_signal_is_acceptable(self):
        self.assertTrue(runner.exit_is_acceptable(-self.TERM, delivered_signals={self.TERM}))
        self.assertTrue(runner.exit_is_acceptable(
            -self.KILL, delivered_signals={self.TERM, self.KILL}))

    def test_a_signal_death_the_harness_did_not_cause_is_not(self):
        self.assertFalse(runner.exit_is_acceptable(-self.TERM, delivered_signals=set()))
        self.assertFalse(runner.exit_is_acceptable(-self.KILL, delivered_signals={self.TERM}))

    def test_a_status_the_process_chose_is_never_acceptable(self):
        # Round 2 found a self-exit racing the kill; round 3 found that the
        # shell's 128+signal convention is just such a self-chosen status.
        for code in (1, 2, 3, 255, 128 + self.TERM, 128 + self.KILL, None):
            with self.subTest(code=code):
                self.assertFalse(runner.exit_is_acceptable(
                    code, delivered_signals={self.TERM, self.KILL}))


class TestRunnerSessionLiveness(unittest.TestCase):
    """A reviewer that prints nothing but keeps writing its session record is
    working, not stalled."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.run_dir = os.path.join(self.tmp.name, "run")
        os.makedirs(self.run_dir)
        self.prompt = os.path.join(self.run_dir, "prompt.txt")
        with open(self.prompt, "w") as fh:
            fh.write("review\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_fake(self, silence, watch):
        env = dict(os.environ, CODEX_REVIEW_HOME=self.home)
        controls = {"FAKE_CODEX_MODE": "silent_recording",
                    "FAKE_CODEX_SILENCE": str(silence)}
        last = os.path.join(self.run_dir, "last.json")
        with mock.patch.object(runner, "SESSION_POLL_INTERVAL", 0.2), \
                mock.patch.object(runner._SessionWatch, "poll",
                                  runner._SessionWatch.poll if watch
                                  else (lambda self, now: None)):
            return runner.run_review(
                cmd=[sys.executable, FAKE, "-o", last, "-"], run_dir=self.run_dir,
                prompt_path=self.prompt, last_message_path=last,
                model="gpt-6-sol", effort="high", stall_timeout=1.0,
                global_deadline=60, env=env, extra_env=controls,
                poll_interval=0.1)

    def test_growing_record_keeps_a_silent_reviewer_alive(self):
        result = self.run_fake(silence=3, watch=True)
        self.assertEqual(result.state, "CLEAN", result.error)

    def test_without_the_record_the_same_silence_is_a_stall(self):
        result = self.run_fake(silence=3, watch=False)
        self.assertEqual((result.state, result.failure_kind), ("STALLED", "stall"))
        with open(os.path.join(self.run_dir, "result.json")) as fh:
            self.assertEqual(json.load(fh)["state"], "STALLED")


if __name__ == "__main__":
    unittest.main()
