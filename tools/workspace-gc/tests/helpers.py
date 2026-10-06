"""Temporary git fixtures: a fake network host, main checkouts, workspaces.

`git@net.test:<name>.git` is a network URL to workspace-gc, but a global
`url.<base>.insteadOf` rule (in a private GIT_CONFIG_GLOBAL) makes git reach a
local bare repository for it, so ls-remote, clone and push work offline.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from workspace_gc import git as git_mod
from workspace_gc.signals import Signals, SourceStatus, WorkRef

NET = "git@net.test:"


def sh(*args, cwd=None, input=None):
    proc = subprocess.run(args, cwd=cwd, input=input, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"{args} failed: {proc.stderr}")
    return proc.stdout


def ok_signals(**kw):
    s = Signals(**kw)
    for name in ("herdr", "processes", "work"):
        s.status.setdefault(name, SourceStatus("ok"))
    return s


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="wsgc-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.net = os.path.join(self.tmp, "net")
        self.projects = os.path.join(self.tmp, "projects")
        self.ws = os.path.join(self.tmp, "workspaces")
        for d in (self.net, self.projects, self.ws):
            os.makedirs(d)
        cfg = os.path.join(self.tmp, "gitconfig")
        with open(cfg, "w") as fh:
            fh.write(f'[user]\n\tname = Test\n\temail = test@example.invalid\n'
                     f'[init]\n\tdefaultBranch = main\n'
                     f'[url "file://{self.net}/"]\n\tinsteadOf = {NET}\n'
                     f'[advice]\n\tdetachedHead = false\n')
        saved = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
        os.environ["GIT_CONFIG_GLOBAL"] = cfg
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        git_mod._base_env = None

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            git_mod._base_env = None
        self.addCleanup(restore)

    # -- builders

    def network_repo(self, name="proj"):
        """Bare 'network' repo with one commit on main; returns its URL."""
        bare = os.path.join(self.net, f"{name}.git")
        sh("git", "init", "-q", "--bare", bare)
        seed = os.path.join(self.tmp, f"seed-{name}")
        sh("git", "clone", "-q", f"{NET}{name}.git", seed)
        self.write(seed, "README.md", "hello\n")
        self.write(seed, ".gitignore", ".venv/\ndb.sqlite3\n.cache/\n")
        sh("git", "add", "-A", cwd=seed)
        sh("git", "commit", "-qm", "init", cwd=seed)
        sh("git", "push", "-q", "origin", "main", cwd=seed)
        shutil.rmtree(seed)
        return f"{NET}{name}.git"

    def main_checkout(self, url, name="proj"):
        path = os.path.join(self.projects, name)
        sh("git", "clone", "-q", url, path)
        return path

    def worktree(self, repo, ws_name, branch, repo_name="proj", start="HEAD"):
        path = os.path.join(self.ws, ws_name, repo_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        sh("git", "-C", repo, "worktree", "add", "-q", "-b", branch, path, start)
        return path

    def clone(self, url_or_path, ws_name, repo_name="proj"):
        path = os.path.join(self.ws, ws_name, repo_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        sh("git", "clone", "-q", url_or_path, path)
        return path

    def commit(self, repo, name="file.txt", text="x\n", msg="change"):
        self.write(repo, name, text)
        sh("git", "add", "-A", cwd=repo)
        sh("git", "commit", "-qm", msg, cwd=repo)
        return sh("git", "rev-parse", "HEAD", cwd=repo).strip()

    @staticmethod
    def write(repo, name, text):
        p = os.path.join(repo, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)

    # -- running

    def build(self, signals=None, **kw):
        from workspace_gc import inventory
        kw.setdefault("main_roots", [self.projects])
        kw.setdefault("keep_file", None)
        kw.setdefault("sizes", False)
        return inventory.build([self.ws], signals or ok_signals(), **kw)

    def by_path(self, inv):
        return {c.path: c for c in inv.checkouts}

    def cli(self, *argv, signals=None):
        import io
        from workspace_gc import cli
        out = io.StringIO()
        base = ["--root", self.ws, "--main-root", self.projects,
                "--keep-file", os.path.join(self.tmp, "no-keep-file"), "--no-sizes"]
        if "--min-idle-hours" not in argv:
            base += ["--min-idle-hours", "0"]
        argv = list(argv)
        cmd = argv[:1] if argv and argv[0] in cli.COMMANDS else ["scan"]
        rest = argv[1:] if cmd == argv[:1] else argv
        code = cli.main(cmd + base + rest, signals=signals or ok_signals(), out=out)
        return code, out.getvalue()


__all__ = ["GitFixture", "ok_signals", "sh", "NET", "WorkRef", "SourceStatus", "Signals"]
