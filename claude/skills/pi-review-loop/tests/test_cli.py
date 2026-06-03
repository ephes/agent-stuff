import os
import shutil
import subprocess
import sys
import tempfile
import unittest

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

    def test_lock_held_exit_three(self):
        lock_dir = os.path.join(self.tmp.name, "lock")
        os.mkdir(lock_dir)
        with open(os.path.join(lock_dir, "meta.json"), "w") as fh:
            fh.write('{"harness_pid": %d, "command": "pi-review-loop"}' % os.getpid())
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", self.repo, "--run-dir", os.path.join(self.tmp.name, "run"),
             "--lock-dir", lock_dir, "--model", "fake/model"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 3, proc.stdout)

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


if __name__ == "__main__":
    unittest.main()
