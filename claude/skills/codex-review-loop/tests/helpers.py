import json
import os
import subprocess
import sys
import tempfile

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(SKILL_ROOT, "tests", "fake_codex.py")
BIN = os.path.join(SKILL_ROOT, "bin", "codex-review-loop")
ENTRY = os.path.join(SKILL_ROOT, "tests", "harness_entry.py")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class RepoFixture:
    """A throwaway repository with one uncommitted change, a private
    CODEX_HOME for the fake, and a private lock pool."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(self.root, "repo")
        self.home = os.path.join(self.root, "codex-home")
        self.lock = os.path.join(self.root, "locks")
        self.ledger = os.path.join(self.root, "ledger")
        os.makedirs(self.repo)
        os.makedirs(self.home)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        self.write("a.py", "print(1)\n")
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-qm", "i")
        self.write("a.py", "print(2)\n")
        self.runs = 0

    def write(self, rel, text):
        with open(os.path.join(self.repo, rel), "w") as fh:
            fh.write(text)

    def cleanup(self):
        self.tmp.cleanup()

    def run(self, mode="clean", *extra, env_extra=None, run_dir=None):
        self.runs += 1
        run_dir = run_dir or os.path.join(self.root, f"run-{self.runs}")
        env = dict(os.environ)
        env.pop("CODEX_REVIEW_MAX_CONCURRENT", None)
        env.update({
            "CODEX_REVIEW_TEST_BIN": f"{sys.executable} {FAKE}",
            "CODEX_REVIEW_HOME": self.home,
            "FAKE_CODEX_MODE": mode,
        })
        env.update(env_extra or {})
        proc = subprocess.run(
            [sys.executable, ENTRY, "--repo", self.repo, "--run-dir", run_dir,
             "--lock-dir", self.lock, "--ledger-dir", self.ledger, *extra],
            capture_output=True, text=True, env=env, timeout=120)
        result_path = os.path.join(run_dir, "result.json")
        result = None
        if os.path.exists(result_path):
            with open(result_path) as fh:
                result = json.load(fh)
        return proc, result, run_dir
