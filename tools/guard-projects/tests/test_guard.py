import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import guard_projects as g


class GuardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Keep the owner's global/system git config (insteadOf, pushDefault)
        # out of push-target resolution.
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                           "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
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
        for url in ["git@github.com:someone-else/repo.git",
                    "https://github.com/ephesx/y",
                    "https://evil.example/ephes/x"]:
            self.assertFalse(g.owner_ok(url), url)

    def test_push_to_foreign_remote_blocked(self):
        def git(*a):
            subprocess.run(["git", "-C", self.ws, *a], check=True,
                           capture_output=True)
        git("init", "-q")
        git("remote", "add", "origin", "git@github.com:someone-else/repo.git")
        git("remote", "add", "mine", "git@github.com:ephes/repo.git")
        self.assertIsNotNone(self.blocked("git push -u origin feat"))
        self.assertIsNone(self.blocked("git push mine feat"))
        cwd = os.getcwd()
        os.chdir(self.ws)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(g.check_push_main(["origin"]), 1)
        self.assertEqual(g.check_push_main(["mine"]), 0)


    def push_repo(self):
        """A throwaway repo on branch main with fake remotes; nothing is pushed."""
        def git(*a):
            subprocess.run(["git", "-C", self.ws, *a], check=True,
                           capture_output=True)
        git("init", "-q")
        git("symbolic-ref", "HEAD", "refs/heads/main")
        git("remote", "add", "origin", "https://github.com/ephes/repo")
        git("remote", "add", "up", "https://github.com/someone-else/repo")
        git("remote", "add", "mixed", "https://github.com/ephes/repo")
        git("config", "remote.mixed.pushurl", "https://github.com/someone-else/repo")
        return git

    def test_push_target_resolution_blocks_foreign_targets(self):
        git = self.push_repo()
        for cmd in [
            "git push -o ci.skip up",
            "git push -oci.skip up main",
            "git push -uo ci.skip up",
            "git push --push-option ci.skip up",
            "git push --repo=up",
            "git push --repo up",
            "git push --rep up",
            "git push --receive-pack git-receive-pack up",
            "git push --force-with-lease up main",
            "git push origin main --repo=up -o x && git push up",
            "git push -- up main",
            "git push mixed main",
            "git push nosuch main",
            "git push https://github.com/someone-else/repo main",
            "git push ../elsewhere main",
            "git push --bogus origin main",
            "git push --re origin",
            "git push -x origin",
            "git push origin -o",
            "git -c remote.origin.pushurl=https://github.com/someone-else/repo push origin",
            "GIT_DIR=/nonexistent/.git git push",
        ]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.blocked(cmd))
        # Bare `git push` follows pushRemote, pushDefault, branch.remote.
        for key in ["branch.main.pushRemote", "remote.pushDefault",
                    "branch.main.remote"]:
            with self.subTest(key=key):
                git("config", key, "up")
                self.assertIsNotNone(self.blocked("git push"))
                self.assertIsNotNone(self.blocked("git push -u"))
                git("config", "--unset", key)
        git("config", "url.https://github.com/someone-else/.pushInsteadOf",
            "https://github.com/ephes/")
        self.assertIsNotNone(self.blocked("git push origin main"))
        self.assertIsNotNone(self.blocked("git push https://github.com/ephes/repo"))

    def test_push_target_resolution_allows_ephes(self):
        git = self.push_repo()
        for cmd in [
            "git push",
            "git push -u origin HEAD",
            "git push -o ci.skip origin main",
            "git push --repo=up origin main",
            "git push --force-with-lease origin main",
            "git push --force-with-lease=main:abc origin main",
            "git push --no-verify --tags origin",
            "git push -- origin main",
            "git push https://github.com/ephes/repo main",
            "git -c branch.main.pushRemote=up -c branch.main.pushRemote=origin push",
        ]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.blocked(cmd))
        for cmd in [f"git -C {self.ws} push origin main",
                    f"git --git-dir {self.ws}/.git push origin main",
                    f"GIT_DIR={self.ws}/.git git push origin"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.blocked(cmd, self.root))
        for cmd in [f"git -C {self.ws} push up",
                    f"git --git-dir={self.ws}/.git push up",
                    f"env GIT_DIR={self.ws}/.git git push mixed"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.blocked(cmd, self.root))
        git("config", "remote.pushDefault", "up")
        git("config", "branch.main.pushRemote", "origin")
        self.assertIsNone(self.blocked("git push"))
        # A single remote is the default even when it is not called origin.
        git("remote", "remove", "origin")
        git("remote", "remove", "mixed")
        git("remote", "remove", "up")
        # (removing a remote also drops pushDefault/pushRemote naming it)
        git("remote", "add", "mine", "git@github.com:ephes/repo.git")
        self.assertIsNone(self.blocked("git push"))
        git("remote", "add", "up", "https://github.com/someone-else/repo")
        # Two remotes, none chosen: git falls back to origin, which is missing.
        self.assertIsNotNone(self.blocked("git push"))

    def test_push_resolution_follows_git_semantics(self):
        git = self.push_repo()
        other = os.path.join(os.path.dirname(self.ws), "ws-y")
        os.makedirs(other)
        subprocess.run(["git", "init", "-q", other], check=True)
        subprocess.run(["git", "-C", other, "remote", "add", "origin",
                        "https://github.com/someone-else/repo"], check=True)
        # --git-dir is resolved after every -C, as git does.
        self.assertIsNotNone(self.blocked(f"git --git-dir=.git -C {other} push origin"))
        self.assertIsNone(self.blocked(f"git -C {other} --git-dir={self.ws}/.git push origin"))
        # Leading assignments reach nested shells; export/unset before a push
        # cannot be followed reliably, so the push is refused.
        for cmd in [f"GIT_DIR={other}/.git bash -c 'git push origin'",
                    f"export GIT_DIR={other}/.git; git push origin",
                    f"true || export GIT_DIR={self.ws}/.git; git push origin",
                    "unset GIT_DIR; git push origin",
                    f"export X=1 && bash -c 'git push origin'"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.blocked(cmd))
        self.assertIsNone(self.blocked(f"GIT_DIR={self.ws}/.git bash -c 'git push origin'",
                                       other))
        # A remote defined only with -c is a remote, not a URL to rewrite.
        self.assertIsNotNone(self.blocked(
            "git -c remote.tmp.url=git@github.com:someone-else/repo.git "
            "-c url.git@github.com:ephes/repo.git.insteadOf=tmp push tmp HEAD"))
        self.assertIsNone(self.blocked(
            "git -c remote.tmp.url=git@github.com:ephes/repo.git push tmp HEAD"))
        # A tag named like the branch does not hide branch.<name>.pushRemote.
        git("-c", "user.name=t", "-c", "user.email=t@example.invalid",
            "commit", "-q", "--allow-empty", "-m", "x")
        git("tag", "main")
        git("config", "branch.main.pushRemote", "up")
        self.assertIsNotNone(self.blocked("git push"))
        # pushInsteadOf only applies to url, insteadOf also to pushurl.
        git("config", "branch.main.pushRemote", "origin")
        git("config", "remote.origin.pushurl", "https://github.com/ephes/repo")
        git("config", "url.https://github.com/someone-else/.pushInsteadOf",
            "https://github.com/ephes/")
        self.assertIsNone(self.blocked("git push"))
        git("config", "url.https://github.com/someone-else/.insteadOf",
            "https://github.com/ephes/")
        self.assertIsNotNone(self.blocked("git push"))

    def test_push_outside_a_repository_fails_closed(self):
        self.assertIsNotNone(self.blocked("git push origin main"))
        self.assertIsNotNone(self.blocked("git push"))

    def test_check_push_remote_resolves_like_git_push(self):
        git = self.push_repo()
        cwd = os.getcwd()
        os.chdir(self.ws)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(g.check_push_main([]), 0)
        self.assertEqual(g.check_push_main(["origin"]), 0)
        self.assertEqual(g.check_push_main(["-u", "origin", "HEAD"]), 0)
        self.assertEqual(g.check_push_main(["mixed"]), 1)
        self.assertEqual(g.check_push_main(["-o", "x", "up"]), 1)
        self.assertEqual(g.check_push_main(["--repo=up"]), 1)
        self.assertEqual(g.check_push_main(["nosuch"]), 1)
        git("config", "branch.main.remote", "up")
        self.assertEqual(g.check_push_main([]), 1)

if __name__ == "__main__":
    unittest.main()
