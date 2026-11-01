import json
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from pi_review_loop import cli, quota


class TestQuotaGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                     ["config", "user.name", "T"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        path = os.path.join(self.repo, "a.py")
        with open(path, "w") as fh:
            fh.write("x = 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=self.repo, check=True, capture_output=True)
        with open(path, "w") as fh:
            fh.write("x = 2\n")
        self.run_dir = os.path.join(self.tmp.name, "run")

    def _main(self, **kw):
        return cli.main(["--repo", self.repo, "--run-dir", self.run_dir,
                         "--lock-dir", os.path.join(self.tmp.name, "lock"),
                         "--model", "fake/model"], **kw)

    def test_used_up_limit_fails_closed_before_pi_starts(self):
        with mock.patch.object(cli, "run_review") as run_review:
            code = self._main(quota_block=lambda: ("PROVIDER_ERROR", "Codex quota guard: Codex weekly limit is at 100%"))
        self.assertEqual(code, 2)
        run_review.assert_not_called()
        with open(os.path.join(self.run_dir, "result.json")) as fh:
            result = json.load(fh)
        self.assertEqual(result["state"], "PROVIDER_ERROR")
        self.assertIn("100%", result["error"])

    def test_default_block_uses_the_guard_without_fake_reviewer(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PI_REVIEW_FAKE_CMD", None)
            with mock.patch.object(quota, "check",
                                   return_value=SimpleNamespace(blocked=True, message="full")):
                self.assertEqual(cli._quota_block(), ("PROVIDER_ERROR", "Codex quota guard: full"))
            with mock.patch.object(quota, "check",
                                   return_value=SimpleNamespace(blocked=False, message="ok")):
                self.assertIsNone(cli._quota_block())
            with mock.patch.object(quota, "check", side_effect=ValueError("bad threshold")):
                state, message = cli._quota_block()
                self.assertEqual(state, "INVALID")
                self.assertTrue(message.startswith(cli.QUOTA_PREFIX))
                self.assertIn("bad threshold", message)

    def test_fake_reviewer_skips_the_guard(self):
        with mock.patch.dict(os.environ, {"PI_REVIEW_FAKE_CMD": "fake"}), \
                mock.patch.object(quota, "check") as check:
            self.assertIsNone(cli._quota_block())
        check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
