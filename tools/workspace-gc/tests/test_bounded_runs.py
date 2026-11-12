"""Bounded runs: step and run time limits, the shared borrowed-objects walk,
bounded parallelism, network timeouts and the run lock."""

import json
import os
import time
import unittest
from unittest import mock

from tests.helpers import GitFixture, ok_signals, sh
from workspace_gc import budget, cli, git as git_mod, inventory, runlock
from workspace_gc import remove as rm_mod


class TestBudget(unittest.TestCase):
    def test_no_step_means_no_limit(self):
        self.assertIsNone(budget.remaining())
        budget.check()
        self.assertEqual(budget.cap(42), 42)

    def test_expired_step_raises_and_caps(self):
        with budget.step(0.05):
            self.assertLessEqual(budget.cap(600), 0.05)
            time.sleep(0.1)
            with self.assertRaises(budget.StepTimeout):
                budget.check()
            with self.assertRaises(budget.StepTimeout):
                budget.cap(600)
        budget.check()  # the limit ends with the step

    def test_nested_step_keeps_earlier_deadline(self):
        with budget.step(0.05):
            with budget.step(100):
                self.assertLessEqual(budget.remaining(), 0.05)

    def test_run_deadline_bounds_step(self):
        with budget.step(100, run_deadline=time.monotonic() + 0.05):
            self.assertLessEqual(budget.remaining(), 0.05)
        with budget.step(0, run_deadline=None):
            self.assertIsNone(budget.remaining())

    def test_unbounded_clears_deadline(self):
        with budget.step(0.01):
            time.sleep(0.02)
            with budget.unbounded():
                budget.check()
                self.assertIsNone(budget.remaining())

    def test_run_clock(self):
        self.assertFalse(budget.RunClock(0).expired())
        self.assertIsNone(budget.RunClock(None).deadline)
        clock = budget.RunClock(0.01)
        time.sleep(0.02)
        self.assertTrue(clock.expired())


class TestGitTimeouts(GitFixture):
    def test_git_is_cut_off_at_the_step_deadline(self):
        start = time.monotonic()
        with budget.step(0.5):
            with self.assertRaisesRegex(git_mod.GitError, "timed out"):
                git_mod.run(["-c", "alias.slow=!sleep 20", "slow"], self.tmp)
        self.assertLess(time.monotonic() - start, 10)

    def test_network_stall_limits_in_environment(self):
        env = git_mod.base_env()
        self.assertEqual(env["GIT_HTTP_LOW_SPEED_LIMIT"], "1000")
        self.assertEqual(env["GIT_HTTP_LOW_SPEED_TIME"], "30")

    def test_ssh_keepalive_when_no_ssh_command_configured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GIT_SSH_COMMAND", None)
            git_mod._base_env = None
            env = git_mod.base_env()
        self.assertIn("ServerAliveInterval=15", env["GIT_SSH_COMMAND"])
        self.assertIn("ConnectTimeout=15", env["GIT_SSH_COMMAND"])


class TestRunLock(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="wsgc-lock-")
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "state", "workspace-gc.lock")

    def test_second_acquire_is_busy_and_names_holder(self):
        first = runlock.acquire(self.path)
        try:
            with self.assertRaisesRegex(runlock.Busy, f"pid {os.getpid()}"):
                runlock.acquire(self.path)
        finally:
            first.release()
        runlock.acquire(self.path).release()  # free again after release

    def test_lock_of_a_dead_holder_is_free(self):
        import subprocess
        import sys
        code = ("import sys; sys.path.insert(0, sys.argv[1]);"
                "from workspace_gc import runlock; runlock.acquire(sys.argv[2])")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run([sys.executable, "-c", code, root, self.path], check=True, timeout=30)
        runlock.acquire(self.path).release()


class TestBoundedApply(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def test_borrowed_objects_walk_is_shared_between_removals(self):
        clones = [self.clone(self.url, f"ws-c{i}") for i in range(3)]
        real = inventory.lending_scope
        with mock.patch.object(inventory, "lending_scope", side_effect=real) as walk:
            code, out = self.cli("--apply")
        self.assertEqual(code, 0, out)
        for c in clones:
            self.assertFalse(os.path.exists(c), c)
        # one walk for the inventory, one shared by all three removals
        self.assertEqual(walk.call_count, 2)

    def test_lending_ttl_zero_walks_per_removal(self):
        clones = [self.clone(self.url, f"ws-c{i}") for i in range(3)]
        real = inventory.lending_scope
        with mock.patch.object(inventory, "lending_scope", side_effect=real) as walk, \
                mock.patch.object(rm_mod, "lending_scope", side_effect=real) as direct:
            code, out = self.cli("--apply", "--lending-ttl", "0")
        self.assertEqual(code, 0, out)
        for c in clones:
            self.assertFalse(os.path.exists(c), c)
        self.assertEqual(walk.call_count + direct.call_count, 4)

    def test_cached_walk_still_refuses_a_borrowed_clone(self):
        lender = self.clone(self.url, "ws-lender")
        co = self.by_path(self.build())[lender]
        self.assertEqual(co.cls, "A")
        borrower = os.path.join(self.ws, "ws-borrower", "proj")
        os.makedirs(os.path.dirname(borrower))
        sh("git", "clone", "-q", "--shared", lender, borrower)
        cache = inventory.LendingCache([self.ws], [self.projects], [], ttl=600)
        with self.assertRaisesRegex(rm_mod.Refused, "borrowed"):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [], lending=cache)
        self.assertTrue(os.path.isdir(lender))
        self.assertEqual(cache.walks, 1)

    def test_lending_walk_out_of_time_refuses(self):
        lender = self.clone(self.url, "ws-lender")
        co = self.by_path(self.build())[lender]

        def slow(*args, **kw):
            time.sleep(0.2)
            budget.check()
        cache = inventory.LendingCache([self.ws], [self.projects], [], ttl=600, timeout=0.05)
        with mock.patch.object(inventory, "lending_scope", side_effect=slow):
            with self.assertRaisesRegex(rm_mod.Refused, "did not finish in time"):
                rm_mod.remove_checkout(co, [self.ws], [self.projects], [], lending=cache)
            # the failure is cached: no second walk within the ttl
            with self.assertRaises(rm_mod.Refused):
                rm_mod.remove_checkout(co, [self.ws], [self.projects], [], lending=cache)
        self.assertEqual(cache.walks, 1)
        self.assertTrue(os.path.isdir(lender))

    def test_inspection_out_of_time_is_class_c(self):
        wt = self.worktree(self.main, "ws-a", "feat/a")
        real = inventory.inspect

        def slow(co, *args, **kw):
            real(co, *args, **kw)
            time.sleep(0.2)
            budget.check()
            return co
        with mock.patch.object(inventory, "inspect", side_effect=slow):
            co = self.by_path(self.build(step_timeout=0.05))[wt]
        self.assertEqual(co.cls, "C")
        self.assertIn("ran out of time", co.reasons[0])

    def test_checkouts_after_run_deadline_are_not_inspected(self):
        wt = self.worktree(self.main, "ws-a", "feat/a")
        with mock.patch.object(inventory, "inspect") as insp:
            co = self.by_path(self.build(run_deadline=time.monotonic() - 1))[wt]
        insp.assert_not_called()
        self.assertEqual(co.cls, "C")
        self.assertIn("run time limit", co.reasons[0])

    def test_recheck_out_of_time_refuses_and_keeps(self):
        cl = self.clone(self.url, "ws-cl")
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "A")
        real = rm_mod.sig_mod.refresh

        def slow(previous):
            time.sleep(0.3)
            return real(previous)
        with mock.patch.object(rm_mod.sig_mod, "refresh", side_effect=slow):
            with self.assertRaisesRegex(rm_mod.Refused, "out of time|timed out"):
                rm_mod.remove_checkout(co, [self.ws], [self.projects], [], step_timeout=0.25)
        self.assertTrue(os.path.isdir(cl))

    def test_deletion_itself_runs_without_deadline(self):
        cl = self.clone(self.url, "ws-cl")
        co = self.by_path(self.build())[cl]
        seen = []
        real = rm_mod._delete_clone

        def record(path, expected, *rest):
            seen.append(budget.remaining())
            return real(path, expected, *rest)
        with mock.patch.object(rm_mod, "_delete_clone", side_effect=record):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [], step_timeout=300)
        self.assertEqual(seen, [None])
        self.assertFalse(os.path.exists(cl))

    def test_run_time_limit_stops_removals_and_still_reports(self):
        cl = self.clone(self.url, "ws-cl")
        empty = os.path.join(self.ws, "ws-empty")
        os.makedirs(empty)
        out_dir = os.path.join(self.tmp, "state")
        with mock.patch.object(budget.RunClock, "expired", return_value=True):
            code, out = self.cli("report", "--apply", "--out-dir", out_dir)
        self.assertEqual(code, 1, out)
        self.assertTrue(os.path.isdir(cl))
        self.assertTrue(os.path.isdir(empty))
        self.assertIn("stopped early: run time limit reached", out)
        with open(os.path.join(out_dir, "latest.json")) as fh:
            data = json.load(fh)
        self.assertEqual(data["stopped"], "run time limit reached")
        self.assertEqual(data["totals"]["A"]["count"], 1)
        self.assertIn("run time limit", data["skipped"][0]["outcome"])

    def test_run_time_limit_after_removals_exits_1(self):
        cl = self.clone(self.url, "ws-cl")
        empty = os.path.join(self.ws, "ws-empty")
        os.makedirs(empty)
        # a dirty worktree makes its owning repository a pending prune target
        self.write(self.worktree(self.main, "ws-dirty", "feat/dirty"), "new.txt", "x")
        out_dir = os.path.join(self.tmp, "state")
        # not expired while building and removing, expired right after
        with mock.patch.object(budget.RunClock, "expired",
                               side_effect=[False, False, False, True, True, True]):
            code, out = self.cli("report", "--apply", "--out-dir", out_dir)
        self.assertEqual(code, 1, out)
        self.assertFalse(os.path.exists(cl))
        self.assertTrue(os.path.isdir(empty))
        self.assertIn("stopped early: run time limit reached", out)
        self.assertNotIn("skipped", out.split("stopped early")[0])

    def test_shared_remote_lookup_ignores_the_callers_step(self):
        ins = inventory.Inspector([self.projects])
        try:
            with budget.step(0.01):
                time.sleep(0.02)
                shas, err = ins.ls_remote(self.url)
                head = ins.default_head(self.url)
            self.assertTrue(shas, err)
            self.assertEqual(head[0], "main")
        finally:
            ins.close()
        ins = inventory.Inspector([self.projects], run_deadline=time.monotonic() - 1)
        try:
            shas, err = ins.ls_remote(self.url)
            self.assertIsNone(shas)
            self.assertIn("time limit", err)
        finally:
            ins.close()

    def test_lending_snapshot_age_counts_from_walk_start(self):
        def slow(*args, **kw):
            time.sleep(0.3)
            return {}, []
        cache = inventory.LendingCache([self.ws], [self.projects], [], ttl=0.2)
        with mock.patch.object(inventory, "lending_scope", side_effect=slow):
            cache.get()
            cache.get()   # the first snapshot is already older than the ttl
        self.assertEqual(cache.walks, 2)

    def test_empty_dir_removal_stops_at_run_time_limit(self):
        from workspace_gc import empties
        os.makedirs(os.path.join(self.ws, "ws-e1"))
        os.makedirs(os.path.join(self.ws, "ws-e2"))
        later = time.time() + 30 * 24 * 3600
        self.addCleanup(setattr, empties, "_now", empties._now)
        empties._now = lambda: later
        entries = empties.scan([self.ws], [], ok_signals())
        self.assertEqual(sum(e.removable for e in entries), 2)
        calls = iter([False, True])
        empties.remove(entries, [], ok_signals(), expired=lambda: next(calls))
        self.assertEqual([e.removed for e in entries], [True, False])
        self.assertEqual(entries[1].reason, "run time limit reached")
        self.assertTrue(os.path.isdir(os.path.join(self.ws, "ws-e2")))

    def test_husk_scan_out_of_time_is_marked_incomplete(self):
        from workspace_gc import husks
        out_dir = os.path.join(self.tmp, "state")
        os.makedirs(os.path.join(self.ws, "ws-notes"))
        self.write(os.path.join(self.ws, "ws-notes"), "notes.md", "x")

        def slow(*args, **kw):
            raise budget.StepTimeout("time limit reached")
        with mock.patch.object(husks, "scan", side_effect=slow):
            code, out = self.cli("report", "--out-dir", out_dir)
        self.assertEqual(code, 0, out)
        with open(os.path.join(out_dir, "latest.json")) as fh:
            data = json.load(fh)
        self.assertTrue(data["incomplete"])
        with open(os.path.join(out_dir, "latest.txt")) as fh:
            self.assertIn("INCOMPLETE: workspace directories without a checkout", fh.read())

    def test_expiry_with_nothing_left_is_not_a_stop(self):
        cl = self.clone(self.url, "ws-cl")
        with mock.patch.object(budget.RunClock, "expired",
                               side_effect=[False, False, False, True, True, True]):
            code, out = self.cli("--apply")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(cl))
        self.assertNotIn("stopped early", out)

    def test_scan_apply_says_why_it_stopped(self):
        self.clone(self.url, "ws-cl")
        self.write(self.worktree(self.main, "ws-dirty", "feat/dirty"), "new.txt", "x")
        with mock.patch.object(budget.RunClock, "expired",
                               side_effect=[False, False, False, True, True, True]):
            code, out = self.cli("--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("stopped early: run time limit reached", out)

    def test_report_is_busy_while_another_run_holds_the_lock(self):
        out_dir = os.path.join(self.tmp, "state")
        cl = self.clone(self.url, "ws-cl")
        held = runlock.acquire(os.path.join(self.tmp, "workspace-gc.lock"))
        try:
            code, out = self.cli("report", "--apply", "--out-dir", out_dir)
            self.assertEqual(code, cli.EXIT_BUSY)
            self.assertIn("BUSY, nothing done", out)
            self.assertIn(f"pid {os.getpid()}", out)
            code, out = self.cli("remove", "--apply", cl)
            self.assertEqual(code, cli.EXIT_BUSY)
            # a dry-run scan needs no lock
            code, out = self.cli()
            self.assertEqual(code, 0, out)
        finally:
            held.release()
        self.assertFalse(os.path.exists(os.path.join(out_dir, "latest.txt")))
        self.assertTrue(os.path.isdir(cl))
        code, out = self.cli("report", "--apply", "--out-dir", out_dir)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(cl))

    def test_jobs_are_bounded(self):
        for bad in ("0", str(inventory.MAX_JOBS + 1)):
            with self.assertRaises(SystemExit):
                cli.parser().parse_args(["scan", "--jobs", bad])
        self.assertEqual(cli.parser().parse_args(["scan", "--jobs", "4"]).jobs, 4)
        with self.assertRaises(SystemExit):
            cli.parser().parse_args(["scan", "--step-timeout", "-1"])


if __name__ == "__main__":
    unittest.main()
