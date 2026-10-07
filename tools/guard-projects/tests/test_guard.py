import io
import json
import os
import subprocess
import tempfile
import unittest

import guard_projects as g


class GuardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = os.path.realpath(tmp.name)
        self.root = os.path.join(base, "projects")
        self.repo = os.path.join(self.root, "repo")
        self.ws = os.path.join(base, "workspaces", "ws-x")
        os.makedirs(self.repo)
        os.makedirs(self.ws)
        with open(os.path.join(self.repo, "f.txt"), "w") as f:
            f.write("x\n")

    def blocked(self, command, cwd=None):
        return g.blocked_reason(command, cwd or self.ws, self.root)

    def test_blocks_writes_into_projects(self):
        r, w = self.repo, self.ws
        for cmd, cwd in [
            ("git commit -m x", r),
            ("git stash", r),
            ("git pull --ff-only", r),
            ("git restore f.txt", r),
            (f"git -C {r} checkout main", w),
            (f"git -C {r} reset --hard origin/main", w),
            (f"cd {r} && git merge feat", w),
            (f"cd {r}; npm run build", w),
            ("make", r),
            ("uv run pytest", r),
            (f"rm -rf {r}/dist", w),
            ("rm f.txt", r),
            (f"touch {r}/new", w),
            (f"cp a.txt {r}/", w),
            (f"echo hi > {r}/f.txt", w),
            (f"echo hi | tee -a {r}/f.txt", w),
            (f"sed -i '' s/x/y/ {r}/f.txt", w),
            (f"bash -c 'cd {r} && git stash pop'", w),
            (f"env FOO=1 git -C {r} commit -am x", w),
            ("git commit -m x\nls", r),
        ]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.blocked(cmd, cwd))

    def test_allows_reads_and_workspace_writes(self):
        r, w = self.repo, self.ws
        for cmd, cwd in [
            ("git status && git log --oneline -3", r),
            ("git fetch origin", r),
            (f"git -C {r} worktree add {w}/repo -b feat origin/main", w),
            (f"git -C {r} diff", w),
            (f"cat {r}/f.txt | grep x", w),
            (f"cp {r}/f.txt {w}/", w),
            (f"rm -rf {w}/build", w),
            ("make test", w),
            (f"cd {r} && cd {w} && npm run build", w),
            (f"{r}/tools/bin/tool remove --apply {w}", w),
            (f"echo hi > {w}/out.txt", w),
            ("git commit -m 'mention ~/projects in a message'", w),
        ]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.blocked(cmd, cwd))

    def test_hook_exit_codes(self):
        os.environ["GUARD_PROJECTS_ROOT"] = self.root
        self.addCleanup(os.environ.pop, "GUARD_PROJECTS_ROOT")
        def run(payload):
            return g.hook_main(io.StringIO(json.dumps(payload)))
        bad = {"tool_name": "Bash", "cwd": self.repo,
               "tool_input": {"command": "git stash"}}
        self.assertEqual(run(bad), 2)
        self.assertEqual(run({**bad, "cwd": self.ws}), 0)
        self.assertEqual(run({**bad, "tool_name": "Read"}), 0)

    def test_owner_check(self):
        for url in ["git@github.com:ephes/agent-stuff.git",
                    "https://github.com/ephes/work-ledger",
                    "ssh://git@github.com/ephes/x.git"]:
            self.assertTrue(g.owner_ok(url), url)
        for url in ["git@github.com:federfuxx/Heis-Website.git",
                    "https://github.com/ephesx/y",
                    "https://evil.example/ephes/x"]:
            self.assertFalse(g.owner_ok(url), url)

    def test_push_to_foreign_remote_blocked(self):
        def git(*a):
            subprocess.run(["git", "-C", self.ws, *a], check=True,
                           capture_output=True)
        git("init", "-q")
        git("remote", "add", "origin", "git@github.com:federfuxx/Heis-Website.git")
        git("remote", "add", "mine", "git@github.com:ephes/heis.git")
        self.assertIsNotNone(self.blocked("git push -u origin feat"))
        self.assertIsNone(self.blocked("git push mine feat"))
        cwd = os.getcwd()
        os.chdir(self.ws)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(g.check_push_main(["origin"]), 1)
        self.assertEqual(g.check_push_main(["mine"]), 0)


if __name__ == "__main__":
    unittest.main()
