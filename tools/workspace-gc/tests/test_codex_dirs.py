"""Workspace directories of finished Codex work, cache repositories and the
waiting run lock (2026-11-18: ~/workspaces had grown to ~950 dirs)."""

import os
import threading
import time
import unittest
from unittest import mock

from workspace_gc import cli, husks, inventory, runlock

from tests.helpers import GitFixture, ok_signals, sh


class CodexDirFixture(GitFixture):
    def setUp(self):
        super().setUp()
        self.codex = os.path.join(self.tmp, "codex")
        os.makedirs(self.codex)
        env = mock.patch.dict(os.environ, {"WORKSPACE_GC_CODEX_DIR": self.codex})
        env.start()
        self.addCleanup(env.stop)

    def record(self, name, line):
        with open(os.path.join(self.codex, name), "a") as fh:
            fh.write(line + "\n")

    def _later(self, hours):
        orig = husks._now
        husks._now = lambda: time.time() + hours * 3600
        self.addCleanup(setattr, husks, "_now", orig)

    def scan_remove(self, hours, sig=None, **kw):
        sig = sig or ok_signals()
        inv = self.build(signals=sig)
        inv.empty_dirs = []
        self._later(hours)
        hs = {h.path: h for h in husks.scan(inv, sig, sizes=False, **kw)}
        husks.remove(list(hs.values()), inv.roots, inv.keep_patterns, sig,
                     codex_stale_hours=kw.get("codex_stale_hours"))
        return hs


class TestCodexFinishedHusks(CodexDirFixture):
    def test_closed_job_and_clerk_dirs_go_after_6h(self):
        job = os.path.join(self.ws, "ws-cx-cx-r9-proj")
        clerk = os.path.join(self.ws, "ws-merge-cx-r9-proj")
        open_job = os.path.join(self.ws, "ws-cx-cx-r9-other")
        for d in (job, clerk, open_job):
            self.write(d, "review.log", "x")
        self.record("merged.txt", "cx-r9-proj\tproj\tabc1234")
        hs = self.scan_remove(hours=7)
        self.assertTrue(hs[job].removed, hs[job].outcome)
        self.assertIn("cx-r9-proj is merged abc1234", hs[job].codex_finished)
        self.assertTrue(hs[clerk].removed, hs[clerk].outcome)
        self.assertFalse(hs[open_job].stale)           # not closed: 72 h rule
        self.assertTrue(os.path.isdir(open_job))

    def test_closed_job_dir_younger_than_codex_stale_hours_stays(self):
        job = os.path.join(self.ws, "ws-cx-cx-r9-proj")
        self.write(job, "review.log", "x")
        self.record("dropped.txt", "cx-r9-proj\tproj\tnothing to merge")
        hs = self.scan_remove(hours=5)
        self.assertFalse(hs[job].stale)
        self.assertTrue(os.path.isdir(job))

    def test_codex_stale_hours_option(self):
        job = os.path.join(self.ws, "ws-cx-cx-r9-proj")
        self.write(job, "review.log", "x")
        self.record("merged.txt", "cx-r9-proj\tproj\tabc1234")
        hs = self.scan_remove(hours=5, codex_stale_hours=4)
        self.assertTrue(hs[job].removed, hs[job].outcome)

    def test_expanded_scout_round_dir_goes_after_6h(self):
        done = os.path.join(self.ws, "ws-cx-scout7")
        pending = os.path.join(self.ws, "ws-cx-scout8")
        for d in (done, pending):
            self.write(d, "scout-round.md", "x")
        open(os.path.join(self.codex, "round7.archived"), "w").close()
        open(os.path.join(self.codex, "round8.queued"), "w").close()   # not enough
        hs = self.scan_remove(hours=7)
        self.assertTrue(hs[done].removed, hs[done].outcome)
        self.assertEqual(hs[done].codex_finished, "scout round 7 expanded and archived")
        self.assertIn("not archived", hs[pending].kept)
        self.assertFalse(hs[pending].stale)

    def test_uv_cache_repos_and_markers_do_not_block_a_stale_dir(self):
        ws = os.path.join(self.ws, "ws-cachey")
        self.write(ws, "a.log", "x")
        self.uv_checkout(ws)
        os.makedirs(os.path.join(ws, ".cache/uv/git-v0/db/65ee95975e8b3dc7/objects"))
        os.makedirs(os.path.join(ws, ".cache/uv/git-v0/db/65ee95975e8b3dc7/refs"))
        self.write(ws, ".cache/uv/git-v0/db/65ee95975e8b3dc7/HEAD", "ref: refs/heads/main\n")
        # uv drops empty ".git" marker files into its caches: not a repository
        self.write(ws, ".cache/uv/CACHEDIR.TAG", "Signature: 8a477f597d28d172789f06886806bc55")
        self.write(ws, ".cache/uv/sdists-v10/.git", "")
        self.write(ws, ".cache/linux-uv/CACHEDIR.TAG", "Signature: 8a477f597d28d172789f06886806bc55")
        self.write(ws, ".cache/linux-uv/sdists-v9/.git", "")
        hs = self.scan_remove(hours=100)
        self.assertTrue(hs[ws].removed, hs[ws].outcome)
        self.assertFalse(os.path.exists(ws))

    def test_uv_cache_repo_blocks_the_fast_paths(self):
        """A repository under .cache/uv (whatever it holds: no git is run to
        judge it) is accepted only by the ordinary 72 h rule, never by the
        6 h Codex age (review 2026-11-18)."""
        ws = os.path.join(self.ws, "ws-merge-cx-r9-uvrepo")
        self.write(ws, "a.log", "x")
        co = self.uv_checkout(ws)
        self.commit(co, "pkg.py", "x = 2\n", "local only")
        self.record("merged.txt", "cx-r9-uvrepo\tproj\tabc1234")
        hs = self.scan_remove(hours=7)
        self.assertFalse(hs[ws].stale)
        self.assertTrue(os.path.isdir(co))

    def test_unexpanded_scout_round_is_kept(self):
        ws = os.path.join(self.ws, "ws-cx-scout12")
        self.write(ws, "scout-round12.md", "report")
        hs = self.scan_remove(hours=1000)
        self.assertFalse(hs[ws].stale)
        self.assertIn("not archived", hs[ws].kept)
        self.assertTrue(os.path.isdir(ws))

    def test_unreadable_file_blocks(self):
        ws = os.path.join(self.ws, "ws-cx-cx-r9-unread")
        self.write(ws, "notes/secret.md", "x")
        p = os.path.join(ws, "notes/secret.md")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o600)
        self.record("merged.txt", "cx-r9-unread\tproj\tabc1234")
        hs = self.scan_remove(hours=100)
        self.assertFalse(hs[ws].stale)
        self.assertIn("unreadable", hs[ws].note)
        self.assertTrue(os.path.exists(p))

    def test_other_cache_repos_still_block(self):
        ws = os.path.join(self.ws, "ws-prek")
        self.write(ws, "a.log", "x")
        sh("git", "init", "-q", os.path.join(ws, ".cache/prek/repos/abc"))
        hs = self.scan_remove(hours=100)
        self.assertFalse(hs[ws].stale)
        self.assertTrue(os.path.isdir(ws))

    def test_linked_worktree_inside_cache_blocks(self):
        main = self.main_checkout(self.network_repo())
        ws = os.path.join(self.ws, "ws-wtcache")
        self.write(ws, "a.log", "x")
        # deeper than discovery (depth 3) looks, so the directory is a husk
        wt = os.path.join(ws, ".cache", "a", "b", "wt")
        os.makedirs(os.path.dirname(wt))
        sh("git", "-C", main, "worktree", "add", "-q", "--detach", wt)
        hs = self.scan_remove(hours=100)
        self.assertEqual(hs[ws].worktree_dirs, [".cache/a/b/wt"])
        self.assertFalse(hs[ws].stale)
        self.assertTrue(os.path.isdir(wt))

    def test_repository_outside_cache_still_blocks(self):
        ws = os.path.join(self.ws, "ws-cx-cx-r9-proj")
        self.write(ws, "a.log", "x")
        sh("git", "init", "-q", os.path.join(ws, "reviews", "a", "b", "pair"))
        self.record("merged.txt", "cx-r9-proj\tproj\tabc1234")
        hs = self.scan_remove(hours=100)
        self.assertFalse(hs[ws].stale)


class TestCodexIdleCli(CodexDirFixture):
    def test_default_codex_idle_hours_is_6(self):
        self.assertEqual(inventory.CODEX_MIN_IDLE_HOURS, 6.0)
        a = cli.parser().parse_args(["remove", "x"])
        self.assertEqual(a.codex_idle_hours, 6.0)
        self.assertEqual(a.codex_stale_hours, 6.0)

    def test_runner_removes_a_closed_job_clone_at_once(self):
        url = self.network_repo()
        cl = self.clone(url, "ws-cx-cx-r9-proj", "proj")
        sh("git", "checkout", "-q", "-b", "codex-q/r9-proj", cwd=cl)
        self.commit(cl, name="fix.txt", text="fix\n", msg="fix")
        self.record("merged.txt", "cx-r9-proj\tproj\tabc1234")
        code, out = self.cli("remove", "--apply", cl)
        self.assertEqual(code, 1, out)
        self.assertIn("for a closed Codex job clone", out)
        code, out = self.cli("remove", "--apply", cl, "--codex-idle-hours", "0")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(cl))

    def test_pushed_closed_clone_removal_rereads_the_close_record(self):
        url = self.network_repo()
        cl = self.clone(url, "ws-cx-cx-r9-pushed", "proj")
        self.record("merged.txt", "cx-r9-pushed\tproj\tabc1234")
        inv = self.build(min_idle_hours=48, codex_idle_hours=0)
        co = self.by_path(inv)[cl]
        self.assertEqual(co.cls, "A", co.reasons)         # only thanks to the close record
        open(os.path.join(self.codex, "merged.txt"), "w").close()   # record gone again
        from workspace_gc import remove as rm_mod
        with self.assertRaises(rm_mod.Refused) as cm:
            rm_mod.remove_checkout(co, inv.roots, [self.projects], [], signals=ok_signals())
        self.assertIn("no longer closed", str(cm.exception))
        self.assertTrue(os.path.isdir(cl))


class TestRunLockWait(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="wsgc-lock-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "workspace-gc.lock")

    def test_waits_for_the_holder(self):
        first = runlock.acquire(self.path)
        threading.Timer(0.3, first.release).start()
        t0 = time.monotonic()
        lock = runlock.acquire(self.path, wait=10, poll=0.05)
        lock.release()
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)

    def test_gives_up_after_the_wait(self):
        first = runlock.acquire(self.path)
        try:
            t0 = time.monotonic()
            with self.assertRaisesRegex(runlock.Busy, "waited 0.2s"):
                runlock.acquire(self.path, wait=0.2, poll=0.05)
            self.assertLess(time.monotonic() - t0, 5)
        finally:
            first.release()

    def test_remove_waits_by_default_report_does_not(self):
        held = runlock.acquire(self.path)
        try:
            out = __import__("io").StringIO()
            with mock.patch.object(runlock, "acquire", wraps=runlock.acquire) as acq, \
                    mock.patch.object(cli, "DEFAULT_REMOVE_LOCK_WAIT", 0.2):
                code = cli.main(["remove", "--apply", "/nonexistent", "--lock-file", self.path,
                                 "--no-herdr", "--no-processes", "--no-work"], out=out)
                self.assertEqual(code, cli.EXIT_BUSY, out.getvalue())
                self.assertEqual(acq.call_args.kwargs["wait"], 0.2)
                code = cli.main(["report", "--out-dir", self.dir, "--lock-file", self.path,
                                 "--no-herdr", "--no-processes", "--no-work"], out=out)
                self.assertEqual(code, cli.EXIT_BUSY)
                self.assertEqual(acq.call_args.kwargs["wait"], 0.0)
        finally:
            held.release()

    def test_lock_wait_never_exceeds_max_runtime(self):
        held = runlock.acquire(self.path)
        try:
            out = __import__("io").StringIO()
            for cmd in ("remove",):
                with mock.patch.object(runlock, "acquire", wraps=runlock.acquire) as acq:
                    t0 = time.monotonic()
                    code = cli.main([cmd, "--apply", "/nonexistent", "--lock-file", self.path,
                                     "--lock-wait", "30", "--max-runtime", "0.002",
                                     "--no-herdr", "--no-processes", "--no-work"], out=out)
                    self.assertEqual(code, cli.EXIT_BUSY, out.getvalue())
                    self.assertLessEqual(acq.call_args.kwargs["wait"], 0.12)
                    self.assertLess(time.monotonic() - t0, 5)
        finally:
            held.release()


class TestReviewRound1(CodexDirFixture):
    def test_negative_min_stale_hours_never_means_immediate(self):
        young = os.path.join(self.ws, "ws-young")
        self.write(young, "review.log", "x")
        code, out = self.cli("--apply", "--min-stale-hours", "-1")
        self.assertTrue(os.path.isdir(young), out)
        for opt in ("--codex-stale-hours", "--codex-idle-hours", "--lock-wait"):
            for bad in ("-1", "nan", "inf"):
                with self.assertRaises(SystemExit):
                    cli.parser().parse_args(["remove", "x", opt, bad])

    def test_longer_codex_stale_hours_is_not_capped(self):
        job = os.path.join(self.ws, "ws-cx-cx-r9-proj")
        self.write(job, "review.log", "x")
        self.record("merged.txt", "cx-r9-proj\tproj\tabc1234")
        hs = self.scan_remove(hours=100, codex_stale_hours=168)
        self.assertFalse(hs[job].stale)
        self.assertTrue(os.path.isdir(job))

    def test_shallow_uv_marker_is_no_checkout(self):
        ws = os.path.join(self.ws, "ws-shallow")
        self.write(ws, "a.log", "x")
        # UV_CACHE_DIR=<ws>/.cache: the marker sits within discovery depth
        self.write(ws, ".cache/CACHEDIR.TAG", "Signature: 8a477f597d28d172789f06886806bc55")
        self.write(ws, ".cache/sdists-v10/.git", "")
        self.assertEqual(inventory.discover([self.ws]), [])
        hs = self.scan_remove(hours=100)
        self.assertTrue(hs[ws].removed, hs[ws].outcome)

    def test_only_empty_cache_markers_are_no_checkout(self):
        """Only an empty `.git` in `sdists-vN` next to uv's CACHEDIR.TAG is a
        marker; a truncated or damaged `.git` anywhere else is a repository."""
        for rel, text, tag in (("wt/.git", "", False), ("wt/.git", "garbage", False),
                               (".cache/x/.git", "", True), (".cache/sdists-v1/.git", "", False),
                               (".cache/sdists-v1/.git", "garbage", True),
                               (".cache/sdists-v1/.git", "", "unrelated")):
            ws = os.path.join(self.ws, "ws-gm-" + str(abs(hash((rel, text, tag)))))
            self.write(ws, "a.log", "x")
            self.write(ws, rel, text)
            if tag:
                self.write(ws, ".cache/CACHEDIR.TAG", "unrelated" if tag == "unrelated"
                           else "Signature: 8a477f597d28d172789f06886806bc55")
            self.assertIn(os.path.dirname(os.path.join(ws, rel)),
                          [p for p, _ in inventory.discover([self.ws])], (rel, text))
            sh("rm", "-rf", ws)

    def test_unarchived_empty_scout_dir_is_kept(self):
        from workspace_gc import empties
        ws = os.path.join(self.ws, "ws-cx-scout21")
        os.makedirs(ws)
        orig = empties._now
        empties._now = lambda: time.time() + 100 * 3600
        self.addCleanup(setattr, empties, "_now", orig)
        found = {e.path: e for e in empties.scan([self.ws], [], ok_signals())}
        self.assertIn("not archived", found[ws].reason)
        open(os.path.join(self.codex, "round21.archived"), "w").close()
        found = {e.path: e for e in empties.scan([self.ws], [], ok_signals())}
        self.assertEqual(found[ws].reason, "")

    def test_shallow_cache_clone_stays_a_checkout(self):
        ws = os.path.join(self.ws, "ws-shallow2")
        self.write(ws, "a.log", "x")
        sh("git", "init", "-q", os.path.join(ws, ".cache", "tool"))
        hs = self.scan_remove(hours=100)
        self.assertNotIn(ws, hs)                   # judged as a checkout, never as a husk
        self.assertTrue(os.path.isdir(os.path.join(ws, ".cache", "tool", ".git")))

    def test_min_stale_zero_disables_codex_stale_too(self):
        job = os.path.join(self.ws, "ws-cx-cx-r9-proj")
        self.write(job, "review.log", "x")
        self.record("merged.txt", "cx-r9-proj\tproj\tabc1234")
        for v in (0.0, -1.0):
            hs = self.scan_remove(hours=100, min_stale_hours=v)
            self.assertFalse(hs[job].stale)
        self.assertTrue(os.path.isdir(job))

    def test_git_symlink_counts_as_worktree(self):
        main = self.main_checkout(self.network_repo())
        ws = os.path.join(self.ws, "ws-gitlink")
        self.write(ws, "a.log", "x")
        deep = os.path.join(ws, ".cache", "a", "b", "wt")
        os.makedirs(deep)
        os.symlink(os.path.join(main, ".git"), os.path.join(deep, ".git"))
        hs = self.scan_remove(hours=100)
        self.assertEqual(hs[ws].worktree_dirs, [".cache/a/b/wt"])
        self.assertFalse(hs[ws].stale)
        self.assertTrue(os.path.isdir(deep))

    def test_shallow_worktree_in_cache_is_a_checkout(self):
        main = self.main_checkout(self.network_repo())
        ws = os.path.join(self.ws, "ws-wt2")
        os.makedirs(os.path.join(ws, ".cache"))
        sh("git", "-C", main, "worktree", "add", "-q", "--detach", os.path.join(ws, ".cache", "wt"))
        hs = self.scan_remove(hours=100)
        self.assertNotIn(ws, hs)
        self.assertTrue(os.path.isdir(os.path.join(ws, ".cache", "wt")))

    def test_any_git_file_in_uv_cache_is_never_exempt(self):
        """A `.git` FIFO does not hang the walk; a FIFO, a symlink or a
        damaged non-empty `.git` file under .cache/uv is never exempt."""
        for kind in ("fifo", "link", "damaged"):
            ws = os.path.join(self.ws, "ws-gitkind-" + kind)
            self.write(ws, "a.log", "x")
            d = os.path.join(ws, ".cache", "uv", "a", "b", "wt")
            os.makedirs(d)
            g = os.path.join(d, ".git")
            if kind == "fifo":
                os.mkfifo(g)
            elif kind == "link":
                os.symlink("/etc/hosts", g)
            else:
                self.write(d, ".git", "garbage, no pointer")
                self.write(d, "work.txt", "uncommitted")
            t0 = time.monotonic()
            h = husks.inspect(ws, sizes=False)
            self.assertLess(time.monotonic() - t0, 5)
            self.assertIn(".cache/uv/a/b/wt", h.worktree_dirs, kind)
        hs = self.scan_remove(hours=100)
        for kind in ("fifo", "link", "damaged"):
            ws = os.path.join(self.ws, "ws-gitkind-" + kind)
            self.assertFalse(hs[ws].removed if ws in hs else False, kind)
            self.assertTrue(os.path.isdir(ws), kind)

class TestReviewRound3(CodexDirFixture):
    def test_shallow_cache_repo_blocks(self):
        ws = os.path.join(self.ws, "ws-shallow3")
        self.write(ws, "a.log", "x")
        sh("git", "init", "-q", os.path.join(ws, ".cache", "repo"))
        hs = self.scan_remove(hours=100)
        self.assertFalse(hs[ws].removed if ws in hs else False)
        self.assertTrue(os.path.isdir(os.path.join(ws, ".cache", "repo", ".git")))

    def test_borrowed_cache_repo_blocks(self):
        ws = os.path.join(self.ws, "ws-lender")
        self.write(ws, "a.log", "x")
        lender = os.path.join(ws, ".cache", "a", "b", "repo")
        os.makedirs(lender)
        sh("git", "init", "-q", lender)
        self.commit(lender, msg="only here")
        sh("git", "clone", "-q", "--shared", lender, os.path.join(self.ws, "ws-borrower", "b"))
        hs = self.scan_remove(hours=100)
        self.assertFalse(hs[ws].removed)
        self.assertTrue(os.path.isdir(lender))

    def test_cache_repo_with_linked_worktree_blocks(self):
        ws = os.path.join(self.ws, "ws-wtowner")
        self.write(ws, "a.log", "x")
        repo = os.path.join(ws, ".cache", "a", "b", "repo")
        os.makedirs(repo)
        sh("git", "init", "-q", repo)
        self.commit(repo, msg="c")
        sh("git", "-C", repo, "worktree", "add", "-q", "--detach", os.path.join(self.tmp, "elsewhere"))
        hs = self.scan_remove(hours=100)
        self.assertFalse(hs[ws].removed if ws in hs else False)
        self.assertTrue(os.path.isdir(repo))

