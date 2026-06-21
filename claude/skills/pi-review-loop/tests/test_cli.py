import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(SKILL_ROOT, "tests", "fake_pi.py")


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True,
                           capture_output=True)
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print(1)\n")
        subprocess.run(["git", "add", "a.py"], cwd=self.repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=self.repo, check=True,
                       capture_output=True)
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print(2)\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_exit_zero(self):
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", self.repo, "--run-dir", os.path.join(self.tmp.name, "run"),
             "--lock-dir", os.path.join(self.tmp.name, "lock"),
             "--model", "fake/model"],  # hermetic: skip real `pi --list-models`
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("CLEAN", proc.stdout)

    def test_issues_exit_one(self):
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} issues")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", self.repo, "--run-dir", os.path.join(self.tmp.name, "run"),
             "--lock-dir", os.path.join(self.tmp.name, "lock"), "--model", "fake/model"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("ISSUES", proc.stdout)

    def test_lock_held_exit_three_when_all_slots_busy(self):
        lock_dir = os.path.join(self.tmp.name, "lock")
        slot_dir = os.path.join(lock_dir, "slot-0")
        os.makedirs(slot_dir)
        with open(os.path.join(slot_dir, "meta.json"), "w") as fh:
            fh.write('{"harness_pid": %d, "command": "pi-review-loop"}' % os.getpid())
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", self.repo, "--run-dir", os.path.join(self.tmp.name, "run"),
             "--lock-dir", lock_dir, "--max-concurrent", "1",
             "--model", "fake/model"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 3, proc.stdout)

    def test_uses_free_slot_when_another_slot_is_held(self):
        lock_dir = os.path.join(self.tmp.name, "lock")
        slot_dir = os.path.join(lock_dir, "slot-0")
        os.makedirs(slot_dir)
        with open(os.path.join(slot_dir, "meta.json"), "w") as fh:
            fh.write('{"harness_pid": %d, "command": "pi-review-loop"}' % os.getpid())
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", self.repo, "--run-dir", os.path.join(self.tmp.name, "run"),
             "--lock-dir", lock_dir, "--max-concurrent", "2",
             "--model", "fake/model"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_nonexistent_repo_exits_two_cleanly(self):
        missing = os.path.join(self.tmp.name, "does-not-exist")
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", missing, "--run-dir", os.path.join(self.tmp.name, "run3"),
             "--lock-dir", os.path.join(self.tmp.name, "lock3"), "--model", "fake/model"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        import json
        rp = os.path.join(self.tmp.name, "run3", "result.json")
        self.assertTrue(os.path.exists(rp), "preflight failure must still write result.json")
        with open(rp) as fh:
            self.assertEqual(json.load(fh)["state"], "CRASHED")

    def test_non_git_dir_exits_two_cleanly(self):
        nongit = tempfile.mkdtemp()  # standalone, not under the setUp repo
        self.addCleanup(shutil.rmtree, nongit, ignore_errors=True)
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", nongit, "--run-dir", os.path.join(self.tmp.name, "run2"),
             "--lock-dir", os.path.join(self.tmp.name, "lock2"), "--model", "fake/model"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_empty_worktree_exits_two_without_invoking_reviewer(self):
        subprocess.run(["git", "checkout", "--", "a.py"], cwd=self.repo,
                       check=True, capture_output=True)
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", self.repo, "--run-dir", os.path.join(self.tmp.name, "run4"),
             "--lock-dir", os.path.join(self.tmp.name, "lock4"), "--model", "fake/model"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("empty bundle", proc.stderr)
        import json
        with open(os.path.join(self.tmp.name, "run4", "result.json")) as fh:
            self.assertEqual(json.load(fh)["state"], "INVALID")


class TestPiCmd(unittest.TestCase):
    def test_real_pi_cmd_includes_review_instruction(self):
        from pi_review_loop import cli
        env = {k: v for k, v in os.environ.items() if k != "PI_REVIEW_FAKE_CMD"}
        with mock.patch.dict(os.environ, env, clear=True):
            cmd = cli._pi_cmd("openai-codex/gpt-5.5", "/tmp/bundle.md")
        self.assertEqual(cmd[0], "pi")
        self.assertIn("--mode", cmd)
        self.assertIn("--no-tools", cmd)
        self.assertIn("@/tmp/bundle.md", cmd)
        self.assertIn("--append-system-prompt", cmd)
        i = cmd.index("--append-system-prompt")
        instruction = cmd[i + 1]
        self.assertIn("REVIEW: CLEAN", instruction)
        self.assertIn("REVIEW: ISSUES", instruction)
        self.assertIn("code reviewer", instruction)

    def test_fake_cmd_seam_used_when_env_set(self):
        from pi_review_loop import cli
        with mock.patch.dict(os.environ, {"PI_REVIEW_FAKE_CMD": "echo hi there"}, clear=False):
            self.assertEqual(cli._pi_cmd("m", "/x/b.md"), ["echo", "hi", "there"])


if __name__ == "__main__":
    unittest.main()
