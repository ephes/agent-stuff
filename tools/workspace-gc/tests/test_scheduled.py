"""The scheduled command (`report --apply`) and empty workspace directories."""

import json
import os
import shutil
import subprocess
import time
import types
import unittest

from tests.helpers import GitFixture, SourceStatus, WorkRef, ok_signals
from workspace_gc import cli, empties


class Scheduled(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)
        self.calls = []
        orig = cli.sig_mod.run_work

        def fake(env_file, ledger, args):
            self.calls.append(args)
            return 0, json.dumps({"item": {"requests": []}}), ""
        cli.sig_mod.run_work = fake
        self.addCleanup(setattr, cli.sig_mod, "run_work", orig)
        self.env = os.path.join(self.tmp, "work-env")
        with open(self.env, "w") as fh:
            fh.write("WORK_API_TOKEN=not-used-in-tests\n")
        self.out_dir = os.path.join(self.tmp, "state")

    def report(self, *extra, signals=None):
        code, out = self.cli("report", "--out-dir", self.out_dir, "--work-env", self.env,
                             "--work-ledger", self.tmp, *extra, signals=signals)
        with open(os.path.join(self.out_dir, "latest.txt")) as fh:
            text = fh.read()
        with open(os.path.join(self.out_dir, "latest.json")) as fh:
            data = json.load(fh)
        return code, out, text, data

    def empty(self, name, *nested):
        path = os.path.join(self.ws, name)
        os.makedirs(os.path.join(path, *nested))
        return path

    def later(self, hours=empties.EMPTY_DIR_MIN_AGE_HOURS + 1):
        """Move the clock of the age guard forward: everything that exists
        now is `hours` old afterwards."""
        orig = empties._now
        empties._now = lambda: time.time() + hours * 3600
        self.addCleanup(setattr, empties, "_now", orig)


class TestScheduledApply(Scheduled):
    def test_removes_class_A_only_and_reports_it(self):
        a_wt = self.worktree(self.main, "ws-a", "feat/a")
        a_cl = self.clone(self.url, "ws-aclone")
        b_wt = self.worktree(self.main, "ws-b", "feat/b")
        self.commit(b_wt)
        c_wt = self.worktree(self.main, "ws-c", "feat/c")
        self.write(c_wt, "new.txt", "x")
        d_wt = self.worktree(self.main, "ws-d", "feat/d")
        code, out, text, data = self.report(
            "--apply", "--work-item", "workspace-gc-report",
            signals=ok_signals(herdr_cwds=[d_wt]))
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(a_wt))
        self.assertFalse(os.path.exists(a_cl))
        for p in (b_wt, c_wt, d_wt):
            self.assertTrue(os.path.isdir(p), p)
        self.assertIn("removed 2 checkouts (", out)
        self.assertIn("left: 0 removable (0K), 1 removable after push, 1 need you", out)
        self.assertIn("workspace-gc run, removals applied - ", text)
        self.assertRegex(text, r"## Removed in this run \(2 checkouts, \d+K; 0 empty directories\)")
        removed, remains = text.split("## What remains")
        self.assertIn("ws-a/proj [worktree", removed)
        self.assertIn("ws-aclone/proj [clone", removed)
        self.assertNotIn("ws-a/proj", remains)
        self.assertIn("## B - removable after push (1)", remains)
        self.assertIn("1 commit(s) on no network branch or tag", remains)
        self.assertIn("## C - needs owner (1)", remains)
        self.assertIn("dirty (0 changed, 1 untracked)", remains)
        self.assertIn("## D - keep (1)", remains)
        self.assertEqual(data["mode"], "applied")
        self.assertEqual(sorted(c["path"] for c in data["removed"]), [a_wt, a_cl])
        self.assertEqual(data["totals"]["A"]["count"], 0)
        upsert = self.calls[0]
        self.assertEqual(upsert[upsert.index("--owner") + 1], "workspace-gc")
        self.assertTrue(upsert[upsert.index("--next-action") + 1].startswith("removed 2 checkouts"))

    def test_same_recheck_as_apply_skips_changed_checkout(self):
        wt = self.worktree(self.main, "ws-a", "feat/a")
        orig = cli.rm_mod.remove_checkout

        def dirty_first(co, *args, **kw):
            self.write(co.path, "late.txt", "x")
            return orig(co, *args, **kw)
        cli.rm_mod.remove_checkout = dirty_first
        self.addCleanup(setattr, cli.rm_mod, "remove_checkout", orig)
        code, out, text, data = self.report("--apply")
        self.assertEqual(code, 1)
        self.assertTrue(os.path.isfile(os.path.join(wt, "late.txt")))
        self.assertIn("removed 0 checkouts", out)
        self.assertIn("not removed in this run: checkout is dirty now", text)
        self.assertEqual(len(data["skipped"]), 1)

    def test_refuses_when_a_signal_source_is_unreadable(self):
        for name, status in (("herdr", SourceStatus("error", "exit 1")),
                             ("processes", SourceStatus("error", "lsof exit 1 (partial)")),
                             ("work", SourceStatus("error", "work items truncated: showing 500 "
                                                            "of 644; list may be incomplete")),
                             ("processes", SourceStatus("skipped"))):
            with self.subTest(source=name, status=status.status):
                shutil.rmtree(self.ws)
                os.makedirs(self.ws)
                cl = self.clone(self.url, "ws-a")
                old = self.empty("ws-old")
                self.later()
                sig = ok_signals()
                sig.status[name] = status
                self.calls.clear()
                code, out, text, data = self.report("--apply", "--work-item", "w", signals=sig)
                self.assertEqual(code, 2)
                self.assertTrue(os.path.isdir(cl))
                self.assertTrue(os.path.isdir(old))
                self.assertIn("REFUSED, nothing removed", out)
                self.assertIn("workspace-gc run REFUSED, nothing removed - ", text)
                self.assertIn(f"REFUSED, in-use signals incomplete: {name}: {status.status}", text)
                self.assertNotIn("Removed in this run", text)
                self.assertEqual(data["mode"], "refused")
                self.assertEqual(data["removed"], [])
                upsert = self.calls[0]
                self.assertEqual(upsert[upsert.index("--owner") + 1], "jochen")

    def test_dry_run_removes_nothing(self):
        wt = self.worktree(self.main, "ws-a", "feat/a")
        old = self.empty("ws-old", "nested")
        self.later()
        code, out, text, data = self.report()
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(wt))
        self.assertTrue(os.path.isdir(os.path.join(old, "nested")))
        self.assertIn("1 removable (", out)
        self.assertIn(", 1 empty directory removable", out)
        self.assertIn("workspace-gc dry run - ", text)
        self.assertIn("## Empty workspace directories (1 removable, 0 kept)", text)
        self.assertNotIn("Removed in this run", text)
        self.assertEqual(data["mode"], "dry-run")
        self.assertEqual(data["empty_dirs"],
                         [{"path": old, "removable": True, "removed": False, "reason": ""}])


class TestEmptyDirs(Scheduled):
    def test_old_empty_directories_are_removed(self):
        flat = self.empty("ws-flat")
        deep = self.empty("ws-deep", "a", "b")
        os.makedirs(os.path.join(deep, "c"))
        self.later()
        code, out, text, data = self.report("--apply")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(flat))
        self.assertFalse(os.path.exists(deep))
        self.assertIn("and 2 empty directories; left:", out)
        self.assertIn("ws-flat [empty directory]", text)
        self.assertEqual([e["removed"] for e in data["empty_dirs"]], [True, True])

    def test_scan_apply_removes_them_too(self):
        flat = self.empty("ws-flat")
        self.later()
        code, out = self.cli("--apply")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(flat))
        self.assertIn(f"removed empty directory {flat}", out)

    def test_young_directory_is_kept(self):
        young = self.empty("ws-young")
        code, out, text, data = self.report("--apply")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(young))
        self.assertIn("ws-young - kept: created or changed 0.0h ago (< 6h)", text)
        self.assertIn("and 0 empty directories", out)

    def test_recent_change_inside_keeps_the_directory(self):
        d = self.empty("ws-d", "inner")
        self.later()
        soon = time.time() + empties.EMPTY_DIR_MIN_AGE_HOURS * 3600
        os.utime(os.path.join(d, "inner"), (soon, soon))  # modified an hour "ago"
        self.report("--apply")
        self.assertTrue(os.path.isdir(os.path.join(d, "inner")))

    def test_age_is_the_newest_of_creation_modification_and_change(self):
        st = types.SimpleNamespace
        self.assertEqual(empties._stamp(st(st_mtime=1.0, st_ctime=2.0, st_birthtime=9.0)), 9.0)
        self.assertEqual(empties._stamp(st(st_mtime=9.0, st_ctime=2.0, st_birthtime=1.0)), 9.0)
        self.assertEqual(empties._stamp(st(st_mtime=1.0, st_ctime=9.0, st_birthtime=2.0)), 9.0)
        self.assertEqual(empties._stamp(st(st_mtime=1.0, st_ctime=9.0)), 9.0)  # no birth time

    def test_directories_with_content_are_never_touched(self):
        with_file = self.empty("ws-file", "a")
        self.write(with_file, "a/.DS_Store", "")
        with_link = self.empty("ws-link")
        os.symlink(self.tmp, os.path.join(with_link, "link"))
        plain_file = os.path.join(self.ws, "notes.txt")
        self.write(self.ws, "notes.txt", "x")
        linked = os.path.join(self.ws, "ws-symlink")
        target = os.path.join(self.tmp, "elsewhere")
        os.makedirs(target)
        os.symlink(target, linked)
        self.later()
        code, out, text, data = self.report("--apply")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(with_file, "a", ".DS_Store")))
        self.assertTrue(os.path.islink(os.path.join(with_link, "link")))
        self.assertTrue(os.path.isfile(plain_file))
        self.assertTrue(os.path.islink(linked))
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(data["empty_dirs"], [])

    def test_content_that_appears_before_removal_stays(self):
        d = self.empty("ws-d", "inner")
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)
        self.assertTrue(entries[0].removable)
        self.write(d, "inner/clone-in-progress", "x")
        empties.remove(entries, [], sig)
        self.assertTrue(os.path.isfile(os.path.join(d, "inner", "clone-in-progress")))
        self.assertEqual((entries[0].removed, entries[0].reason), (False, "no longer empty"))

    def test_rmdir_cannot_delete_content(self):
        # Content that appears after the last check: rmdir fails, nothing is lost.
        d = self.empty("ws-d")
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)
        self._after_last_check(lambda: self.write(d, "late.txt", "x"))
        empties.remove(entries, [], sig)
        self.assertTrue(os.path.isfile(os.path.join(d, "late.txt")))
        self.assertFalse(entries[0].removed)
        self.assertIn("rmdir failed", entries[0].reason)

    def test_directory_swapped_for_a_symlink_does_not_lead_outside(self):
        d = self.empty("ws-d", "inner", "x")
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(os.path.join(outside, "x"))
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)
        self.assertTrue(entries[0].removable)

        def swap():
            shutil.rmtree(os.path.join(d, "inner"))
            os.symlink(outside, os.path.join(d, "inner"))
        self._after_last_check(swap)
        empties.remove(entries, [], sig)
        self.assertTrue(os.path.isdir(os.path.join(outside, "x")))
        self.assertTrue(os.path.islink(os.path.join(d, "inner")))
        self.assertIn("rmdir failed", entries[0].reason)

    def _after_last_check(self, change):
        orig = empties.inspect

        def hooked(*args):
            seen = orig(*args)
            change()
            return seen
        empties.inspect = hooked
        self.addCleanup(setattr, empties, "inspect", orig)

    def test_directory_created_after_the_last_check_stays(self):
        # A worker makes its clone destination after the final inspection.
        d = self.empty("ws-d", "inner")
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)
        self.assertTrue(entries[0].removable)
        self._after_last_check(lambda: os.makedirs(os.path.join(d, "inner", "repo")))
        empties.remove(entries, [], sig)
        self.assertTrue(os.path.isdir(os.path.join(d, "inner", "repo")))
        self.assertIn("rmdir failed", entries[0].reason)

    def test_directory_replaced_after_the_last_check_stays(self):
        d = self.empty("ws-d", "inner")
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)

        def replace():
            os.makedirs(os.path.join(d, "new"))   # keeps the old inode from being reused
            os.rmdir(os.path.join(d, "inner"))
            os.rename(os.path.join(d, "new"), os.path.join(d, "inner"))
        self._after_last_check(replace)
        empties.remove(entries, [], sig)
        self.assertTrue(os.path.isdir(os.path.join(d, "inner")))
        self.assertIn("replaced since the inspection", entries[0].reason)

    def test_process_list_is_read_again_for_every_directory(self):
        first = self.empty("ws-1")
        second = self.empty("ws-2")
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)
        answers = [([], SourceStatus("ok")), ([second], SourceStatus("ok"))]
        orig = empties.sig_mod.read_process_cwds
        empties.sig_mod.read_process_cwds = lambda: answers.pop(0)
        self.addCleanup(setattr, empties.sig_mod, "read_process_cwds", orig)
        empties.remove(entries, [], sig)
        self.assertFalse(os.path.exists(first))
        self.assertTrue(os.path.isdir(second))
        self.assertEqual(answers, [])
        self.assertIn("in use (working directory", entries[1].reason)

    def test_keep_pattern_for_a_path_below_a_globbed_workspace(self):
        one = self.empty("ws-one")
        spanned = self.empty("ws-span")
        other = self.empty("other")
        self.later()
        self.report("--apply", "--keep", os.path.join(self.ws, "ws-*", "repo"),
                    "--keep", os.path.join(self.ws, "ws-span*x"))
        self.assertTrue(os.path.isdir(one))
        self.assertTrue(os.path.isdir(spanned))
        self.assertFalse(os.path.exists(other))

    def test_protected_and_keep_listed_are_kept(self):
        planning = self.empty("ws-work-planning")
        kept = self.empty("ws-kept")
        parent = self.empty("ws-parent")       # a keep-listed path below it
        globbed = self.empty("ws-glob-1")
        gone = self.empty("ws-gone")
        self.later()
        code, out, text, data = self.report(
            "--apply", "--keep", kept, "--keep", os.path.join(parent, "repo"),
            "--keep", os.path.join(self.ws, "ws-glob-*"))
        for p in (planning, kept, parent, globbed):
            self.assertTrue(os.path.isdir(p), p)
        self.assertFalse(os.path.exists(gone))
        self.assertIn("ws-work-planning - kept: protected name", text)
        self.assertIn("ws-kept - kept: keep-listed", text)

    def test_working_directory_and_active_work_item_keep_it(self):
        cwd = self.empty("ws-cwd", "sub")
        pane = self.empty("ws-pane")
        item = self.empty("ws-item")
        closed = self.empty("ws-closed")
        self.later()
        sig = ok_signals(
            process_cwds=[os.path.join(cwd, "sub")], herdr_cwds=[pane],
            work_refs=[WorkRef("active-item", "implementing", os.path.join(item, "repo")),
                       WorkRef("closed-item", "merged", os.path.join(closed, "repo"))])
        code, out, text, data = self.report("--apply", signals=sig)
        for p in (cwd, pane, item):
            self.assertTrue(os.path.isdir(p), p)
        self.assertFalse(os.path.exists(closed))
        self.assertIn("ws-cwd - kept: in use (working directory", text)
        self.assertIn("ws-item - kept: active work item: active-item", text)

    @unittest.skipUnless(shutil.which("lsof") or os.path.exists("/usr/sbin/lsof"), "needs lsof")
    def test_process_that_entered_after_the_inventory_keeps_it(self):
        d = self.empty("ws-d")
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)
        self.assertTrue(entries[0].removable)
        proc = subprocess.Popen(["sleep", "60"], cwd=d)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        empties.remove(entries, [], sig)
        self.assertTrue(os.path.isdir(d))
        self.assertIn("in use (working directory", entries[0].reason)

    def test_unreadable_process_list_at_removal_keeps_everything(self):
        d = self.empty("ws-d")
        self.later()
        sig = ok_signals()
        entries = empties.scan([self.ws], [], sig)
        orig = empties.sig_mod.read_process_cwds
        empties.sig_mod.read_process_cwds = lambda: ([], SourceStatus("error", "lsof exit 1"))
        self.addCleanup(setattr, empties.sig_mod, "read_process_cwds", orig)
        empties.remove(entries, [], sig)
        self.assertTrue(os.path.isdir(d))
        self.assertIn("unreadable now", entries[0].reason)

    def test_directory_emptied_by_this_run_waits_for_a_later_run(self):
        wt = self.worktree(self.main, "ws-a", "feat/a")
        self.later()
        code, out, text, data = self.report("--apply")
        self.assertFalse(os.path.exists(wt))
        self.assertTrue(os.path.isdir(os.path.dirname(wt)))
        self.assertIn("removed 1 checkout (", out)
        self.assertIn("and 0 empty directories", out)


if __name__ == "__main__":
    unittest.main()
