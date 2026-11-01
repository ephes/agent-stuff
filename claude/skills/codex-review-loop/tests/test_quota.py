import json
import os
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from codex_review_loop import cli, native, quota
from tests.helpers import BIN, FAKE, RepoFixture

BLOCKED = SimpleNamespace(blocked=True, message="Codex weekly limit is at 100% until later")
OPEN = SimpleNamespace(blocked=False, message="ok")


class TestQuotaGuard(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture()
        self.addCleanup(self.fx.tmp.cleanup)

    def _main(self, run_dir, **kw):
        return cli.main(["--repo", self.fx.repo, "--run-dir", run_dir,
                         "--lock-dir", self.fx.lock, "--ledger-dir", self.fx.ledger], **kw)

    def _result(self, run_dir):
        with open(os.path.join(run_dir, "result.json")) as fh:
            return json.load(fh)

    def test_used_up_limit_fails_closed_before_codex_starts(self):
        run_dir = os.path.join(self.fx.root, "blocked")
        code = self._main(run_dir, codex_bin=[sys.executable, FAKE],
                          extra_env={"CODEX_HOME": self.fx.home},
                          quota_check=lambda: BLOCKED)
        self.assertEqual(code, 2)
        result = self._result(run_dir)
        self.assertEqual(result["state"], "PROVIDER_ERROR")
        self.assertEqual(result["failure_kind"], "quota")
        self.assertIn("100%", result["error"])
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))
        self.assertFalse(os.path.exists(os.path.join(run_dir, "review-root")))

    def test_open_limit_lets_the_review_run(self):
        run_dir = os.path.join(self.fx.root, "open")
        code = self._main(run_dir, codex_bin=[sys.executable, FAKE],
                          extra_env={"CODEX_HOME": self.fx.home},
                          quota_check=lambda: OPEN)
        self.assertNotEqual(self._result(run_dir).get("failure_kind"), "quota")
        self.assertIn(code, (0, 1, 2))

    def test_production_path_always_runs_the_guard(self):
        run_dir = os.path.join(self.fx.root, "prod")
        with mock.patch.object(quota, "check", return_value=BLOCKED) as check, \
                mock.patch.object(native, "resolve") as resolve, \
                mock.patch.dict(os.environ, {"CODEX_REVIEW_HOME": self.fx.home}):
            code = self._main(run_dir)
        self.assertEqual(code, 2)
        check.assert_called_once()
        self.assertEqual(str(check.call_args.kwargs["home"]), self.fx.home)
        resolve.assert_not_called()
        self.assertEqual(self._result(run_dir)["failure_kind"], "quota")

    def test_guard_configuration_error_is_invalid(self):
        run_dir = os.path.join(self.fx.root, "bad")

        def broken():
            raise ValueError("CODEX_QUOTA_MAX_PERCENT must be a number")

        code = self._main(run_dir, codex_bin=[sys.executable, FAKE], quota_check=broken)
        self.assertEqual(code, 2)
        self.assertEqual(self._result(run_dir)["state"], "INVALID")

    def test_installed_entry_point_refuses_on_a_full_reading(self):
        home = os.path.join(self.fx.root, "full-home")
        sessions = os.path.join(home, "sessions", "2026", "11", "01")
        os.makedirs(sessions)
        event = {"timestamp": "2026-11-01T12:00:00Z", "type": "event_msg",
                 "payload": {"rate_limits": {"primary": {
                     "used_percent": 100.0, "window_minutes": 10080,
                     "resets_at": int(time.time()) + 86400}}}}
        with open(os.path.join(sessions, "rollout-a.jsonl"), "w") as fh:
            fh.write(json.dumps(event) + "\n")
        run_dir = os.path.join(self.fx.root, "installed-full")
        empty = os.path.join(self.fx.root, "unrelated-codex-home")
        os.makedirs(empty)
        # The guard follows the home the review spends against
        # (CODEX_REVIEW_HOME), not an unrelated exported CODEX_HOME.
        env = dict(os.environ, CODEX_REVIEW_HOME=home, CODEX_HOME=empty)
        env.pop("CODEX_QUOTA_ALLOW_CREDITS", None)
        proc = subprocess.run([sys.executable, BIN, "--repo", self.fx.repo,
                               "--run-dir", run_dir, "--lock-dir", self.fx.lock],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("paid credits", proc.stderr)
        self.assertEqual(self._result(run_dir)["failure_kind"], "quota")

    def test_loader_points_at_the_shared_tool(self):
        self.assertTrue(quota.GUARD_DIR.endswith(os.path.join("tools", "codex-quota-guard")))
        self.assertTrue(callable(quota.check))


if __name__ == "__main__":
    unittest.main()
