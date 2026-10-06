import json
import os
import shutil
import unittest

from tests.helpers import NET, GitFixture, SourceStatus, ok_signals, sh
from workspace_gc import cli
from workspace_gc import remove as rm_mod


class TestApply(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def test_apply_removes_only_A(self):
        a_wt = self.worktree(self.main, "ws-a", "feat/a")
        a_cl = self.clone(self.url, "ws-aclone")
        b_wt = self.worktree(self.main, "ws-b", "feat/b")
        self.commit(b_wt)
        c_wt = self.worktree(self.main, "ws-c", "feat/c")
        self.write(c_wt, "new.txt", "x")
        d_wt = self.worktree(self.main, "ws-d", "feat/d")
        code, out = self.cli("--apply", signals=ok_signals(herdr_cwds=[d_wt]))
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(a_wt))
        self.assertFalse(os.path.exists(a_cl))
        for p in (b_wt, c_wt, d_wt):
            self.assertTrue(os.path.isdir(p), p)
        # the branch of a removed worktree stays in its repository
        sh("git", "rev-parse", "--verify", "feat/a", cwd=self.main)
        self.assertIn("removed worktree", out)
        self.assertIn("removed clone", out)
        listed = sh("git", "worktree", "list", "--porcelain", cwd=self.main)
        self.assertNotIn(a_wt, listed)

    def test_dry_run_changes_nothing(self):
        a_wt = self.worktree(self.main, "ws-a", "feat/a")
        code, out = self.cli()
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(a_wt))
        self.assertIn("## A - removable (1)", out)

    def test_json_output(self):
        a_wt = self.worktree(self.main, "ws-a", "feat/a")
        code, out = self.cli("--json")
        data = json.loads(out)
        self.assertEqual(data["totals"]["A"]["count"], 1)
        self.assertEqual(data["checkouts"][0]["path"], a_wt)
        self.assertNotIn("alternates", data["checkouts"][0])

    def test_apply_refused_when_a_signal_failed(self):
        a_wt = self.worktree(self.main, "ws-a", "feat/a")
        sig = ok_signals()
        sig.status["work"] = SourceStatus("error", "HTTP 500")
        code, out = self.cli("--apply", signals=sig)
        self.assertEqual(code, 2)
        self.assertIn("REFUSED --apply", out)
        self.assertTrue(os.path.isdir(a_wt))

    def test_apply_refused_when_signal_skipped(self):
        a_wt = self.worktree(self.main, "ws-a", "feat/a")
        sig = ok_signals()
        sig.status["herdr"] = SourceStatus("skipped")
        code, _ = self.cli("--apply", signals=sig)
        self.assertEqual(code, 2)
        self.assertTrue(os.path.isdir(a_wt))

    def test_default_idle_guard_keeps_fresh_checkouts(self):
        a_wt = self.worktree(self.main, "ws-a", "feat/a")
        code, out = self.cli("--apply", "--min-idle-hours", "48")
        self.assertTrue(os.path.isdir(a_wt))
        self.assertIn("0 removed", out)

    def test_prune_stale_entries(self):
        gone = self.worktree(self.main, "ws-gone", "gone")
        keep = self.worktree(self.main, "ws-keep", "keep")
        self.write(keep, "dirty.txt", "x")
        shutil.rmtree(gone)
        code, out = self.cli()
        self.assertIn("Stale worktree entries", out)
        self.assertIn("ws-gone", sh("git", "worktree", "list", cwd=self.main))
        self.cli("--apply")
        self.assertNotIn("ws-gone", sh("git", "worktree", "list", cwd=self.main))
        self.assertTrue(os.path.isdir(keep))


class TestGuards(GitFixture):
    """Facts change between inventory and removal: removal must re-check."""

    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def _co(self, path):
        inv = self.build()
        co = self.by_path(inv)[path]
        self.assertEqual(co.cls, "A", co.reasons)
        return co

    def _remove(self, co):
        return rm_mod.remove_checkout(co, [self.ws], [self.projects], [])

    def test_worktree_dirtied_after_inventory(self):
        wt = self.worktree(self.main, "ws-a", "a")
        co = self._co(wt)
        self.write(wt, "late.txt", "x")
        with self.assertRaisesRegex(rm_mod.Refused, "dirty"):
            self._remove(co)
        self.assertTrue(os.path.isdir(wt))

    def test_clone_committed_after_inventory(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._co(cl)
        self.commit(cl)
        with self.assertRaisesRegex(rm_mod.Refused, "HEAD moved"):
            self._remove(co)
        self.assertTrue(os.path.isdir(cl))

    def test_clone_side_branch_after_inventory(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._co(cl)
        sh("git", "branch", "side", cwd=cl)
        sh("git", "checkout", "-q", "side", cwd=cl)
        self.commit(cl)
        sh("git", "checkout", "-q", "main", cwd=cl)
        with self.assertRaisesRegex(rm_mod.Refused, "not on a network remote"):
            self._remove(co)
        self.assertTrue(os.path.isdir(cl))

    def test_clone_stash_after_inventory(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._co(cl)
        self.write(cl, "README.md", "s\n")
        sh("git", "stash", "-q", cwd=cl)
        with self.assertRaisesRegex(rm_mod.Refused, "stash"):
            self._remove(co)

    def test_remote_branch_deleted_after_inventory(self):
        wt = self.worktree(self.main, "ws-a", "a")
        self.commit(wt)
        sh("git", "push", "-q", "origin", "a", cwd=wt)
        co = self._co(wt)
        sh("git", "push", "-q", "origin", "--delete", "a", cwd=wt)
        with self.assertRaisesRegex(rm_mod.Refused, "not on a network remote"):
            self._remove(co)

    def test_remote_unreachable_at_removal(self):
        cl = self.clone(self.url, "ws-cl")
        sh("git", "checkout", "-q", "-b", "pushed", cwd=cl)
        self.commit(cl)
        sh("git", "push", "-q", "origin", "pushed", cwd=cl)
        co = self._co(cl)
        os.rename(os.path.join(self.net, "proj.git"), os.path.join(self.net, "moved.git"))
        with self.assertRaises(rm_mod.Refused):
            self._remove(co)
        self.assertTrue(os.path.isdir(cl))

    def test_device_backup_after_inventory(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._co(cl)
        self.write(cl, ".cache/device-db-backups/x/db", "x")
        with self.assertRaisesRegex(rm_mod.Refused, "device"):
            self._remove(co)

    def test_path_swapped_for_symlink(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._co(cl)
        moved = os.path.join(self.tmp, "elsewhere")
        os.rename(cl, moved)
        os.symlink(moved, cl)
        with self.assertRaisesRegex(rm_mod.Refused, "symlink"):
            self._remove(co)
        self.assertTrue(os.path.isdir(moved))

    def test_outside_roots_refused(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._co(cl)
        with self.assertRaisesRegex(rm_mod.Refused, "not inside a root"):
            rm_mod.remove_checkout(co, [os.path.join(self.tmp, "other")], [self.projects], [])

    def test_non_A_refused(self):
        wt = self.worktree(self.main, "ws-b", "b")
        self.commit(wt)
        co = self.by_path(self.build())[wt]
        with self.assertRaisesRegex(rm_mod.Refused, "only class A"):
            self._remove(co)


class TestRemoveCommand(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def test_dry_run_then_apply(self):
        wt = self.worktree(self.main, "ws-item", "item")
        code, out = self.cli("remove", wt)
        self.assertEqual(code, 0)
        self.assertIn("WOULD remove", out)
        self.assertTrue(os.path.isdir(wt))
        code, out = self.cli("remove", "--apply", wt)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(wt))

    def test_remove_ignores_idle_guard_by_default(self):
        wt = self.worktree(self.main, "ws-item", "item")
        code, out = self.cli("remove", "--apply", wt, "--min-idle-hours", "0")
        self.assertEqual(code, 0, out)

    def test_refuses_unpushed(self):
        wt = self.worktree(self.main, "ws-item", "item")
        self.commit(wt, msg="unpushed")
        code, out = self.cli("remove", "--apply", wt)
        self.assertEqual(code, 1)
        self.assertIn("class B", out)
        self.assertTrue(os.path.isdir(wt))

    def test_refuses_outside_root_and_main_checkout(self):
        code, out = self.cli("remove", "--apply", self.main)
        self.assertEqual(code, 1)
        self.assertIn("not inside a root", out)
        self.assertTrue(os.path.isdir(self.main))

    def test_refuses_keep_listed(self):
        wt = self.worktree(self.main, "ws-item", "item")
        code, out = self.cli("remove", "--apply", wt, "--keep", os.path.dirname(wt))
        self.assertEqual(code, 1)
        self.assertIn("keep-listed", out)

    def test_refuses_symlink_argument(self):
        wt = self.worktree(self.main, "ws-item", "item")
        link = os.path.join(self.ws, "link")
        os.symlink(wt, link)
        code, out = self.cli("remove", "--apply", link)
        self.assertEqual(code, 1)
        self.assertIn("symlink", out)
        self.assertTrue(os.path.isdir(wt))

    def test_refuses_with_failed_signal(self):
        wt = self.worktree(self.main, "ws-item", "item")
        sig = ok_signals()
        sig.status["processes"] = SourceStatus("error", "x")
        code, _ = self.cli("remove", "--apply", wt, signals=sig)
        self.assertEqual(code, 2)
        self.assertTrue(os.path.isdir(wt))


class TestReport(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)
        self.calls = []
        self.requests = []
        self.orig = cli.sig_mod.run_work

        def fake(env_file, ledger, args):
            self.calls.append(args)
            if args[0] == "show":
                return 0, json.dumps({"item": {"requests": self.requests}}), ""
            return 0, "{}", ""
        cli.sig_mod.run_work = fake
        self.addCleanup(setattr, cli.sig_mod, "run_work", self.orig)
        self.env = os.path.join(self.tmp, "work-env")
        with open(self.env, "w") as fh:
            fh.write("WORK_API_TOKEN=not-used-in-tests\n")
        self.out_dir = os.path.join(self.tmp, "state")

    def report(self, *extra):
        return self.cli("report", "--out-dir", self.out_dir, "--work-env", self.env,
                        "--work-ledger", self.tmp, *extra)

    def test_writes_files_and_never_removes(self):
        wt = self.worktree(self.main, "ws-a", "a")
        code, out = self.report()
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(wt))
        with open(os.path.join(self.out_dir, "latest.txt")) as fh:
            self.assertIn("1 removable", fh.read())
        with open(os.path.join(self.out_dir, "latest.json")) as fh:
            self.assertEqual(json.load(fh)["totals"]["A"]["count"], 1)
        self.assertEqual(self.calls, [])  # no --work-item, no work calls
        self.assertEqual(sorted(os.listdir(self.out_dir)), ["latest.json", "latest.txt"])

    def test_report_has_no_apply_option(self):
        with self.assertRaises(SystemExit):
            cli.parser().parse_args(["report", "--out-dir", "x", "--apply"])

    def test_item_upsert_and_ask_when_removable(self):
        self.worktree(self.main, "ws-a", "a")
        code, out = self.report("--work-item", "workspace-gc-report")
        self.assertEqual(code, 0, out)
        kinds = [c[0] for c in self.calls]
        self.assertEqual(kinds, ["upsert", "show", "ask"])
        upsert = self.calls[0]
        summary = [a for a in upsert if a.startswith("1 removable")]
        self.assertEqual(len(summary), 1, upsert)
        self.assertRegex(summary[0], r"^1 removable \(\d+(K|M)\), 0 removable after push, "
                                     r"0 need you")
        ask = " ".join(self.calls[2])
        self.assertRegex(ask, r"class-A checkouts \(\d+(K|M)\) listed in")
        self.assertNotIn("GB", ask)
        self.assertEqual(upsert[upsert.index("--owner") + 1], "jochen")
        self.assertNotIn("not-used-in-tests", " ".join(sum(self.calls, [])))

    def test_no_second_ask_when_open(self):
        self.worktree(self.main, "ws-a", "a")
        self.requests = [{"id": 7, "status": "open", "kind": "approval",
                          "text": "Remove ... with workspace-gc --apply?"}]
        self.report("--work-item", "workspace-gc-report")
        self.assertEqual([c[0] for c in self.calls], ["upsert", "show"])

    def test_withdraw_when_nothing_removable(self):
        self.requests = [{"id": 7, "status": "open", "kind": "approval",
                          "text": "Remove ... with workspace-gc --apply?"},
                         {"id": 8, "status": "open", "kind": "question", "text": "other"}]
        self.report("--work-item", "workspace-gc-report")
        self.assertEqual(self.calls[-1], ["withdraw", "7"])
        upsert = self.calls[0]
        self.assertEqual(upsert[upsert.index("--owner") + 1], "workspace-gc")

    def test_absent_env_file_is_tolerated(self):
        code, out = self.cli("report", "--out-dir", self.out_dir, "--work-env",
                             os.path.join(self.tmp, "nope"), "--work-item", "x")
        self.assertEqual(code, 0)
        self.assertIn("not updated", out)
        self.assertEqual(self.calls, [])


class TestLessonsFromCleanup(GitFixture):
    """Regressions from the 2026-10-05 one-off cleanup run."""

    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def advance_network(self, tag_current=False):
        """Push a new main commit (and optionally tag the current one) from a
        scratch clone, so local clones lack the new remote tip object."""
        scratch = os.path.join(self.tmp, "scratch")
        sh("git", "clone", "-q", self.url, scratch)
        if tag_current:
            sh("git", "tag", "-a", "-m", "release", "0.1", cwd=scratch)
            sh("git", "push", "-q", "origin", "0.1", cwd=scratch)
        self.commit(scratch, name="new.txt", msg="newer upstream")
        sh("git", "push", "-q", "origin", "main", cwd=scratch)
        shutil.rmtree(scratch)

    # 1. alternates

    def test_lender_clone_is_kept_while_borrowed(self):
        lender = self.clone(self.url, "ws-lender")
        borrower = os.path.join(self.ws, "ws-borrower", "proj")
        os.makedirs(os.path.dirname(borrower))
        sh("git", "clone", "-q", "--shared", lender, borrower)
        cos = self.by_path(self.build())
        self.assertEqual(cos[lender].cls, "D")
        self.assertIn(borrower, cos[lender].borrowed_by)
        self.assertEqual(cos[borrower].cls, "A", cos[borrower].reasons)
        self.assertTrue(cos[borrower].borrows_from)
        code, out = self.cli("--apply")
        self.assertTrue(os.path.isdir(lender))
        self.assertFalse(os.path.exists(borrower))
        # the next run may remove the lender
        self.cli("--apply")
        self.assertFalse(os.path.exists(lender))

    def test_lender_borrowed_from_main_root_is_kept(self):
        lender = self.clone(self.url, "ws-lender")
        borrower = os.path.join(self.projects, "borrower")
        sh("git", "clone", "-q", "--reference", lender, self.url, borrower)
        self.assertEqual(self.by_path(self.build())[lender].cls, "D")

    def test_borrower_created_after_inventory_blocks_removal(self):
        lender = self.clone(self.url, "ws-lender")
        co = self.by_path(self.build())[lender]
        self.assertEqual(co.cls, "A")
        borrower = os.path.join(self.ws, "ws-borrower", "proj")
        os.makedirs(os.path.dirname(borrower))
        sh("git", "clone", "-q", "--shared", lender, borrower)
        with self.assertRaisesRegex(rm_mod.Refused, "borrowed"):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertTrue(os.path.isdir(lender))

    def test_broken_alternates_is_unknown_not_a_number(self):
        lender = self.clone(self.url, "ws-lender")
        borrower = os.path.join(self.ws, "ws-borrower", "proj")
        os.makedirs(os.path.dirname(borrower))
        sh("git", "clone", "-q", "--shared", lender, borrower)
        shutil.rmtree(lender)
        co = self.by_path(self.build())[borrower]
        self.assertEqual(co.cls, "C")
        self.assertTrue(co.reasons[0].startswith("not inspectable"), co.reasons)

    def test_git_failure_in_guard_refuses(self):
        cl = self.clone(self.url, "ws-cl")
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "A")
        shutil.rmtree(os.path.join(cl, ".git", "objects"))
        os.makedirs(os.path.join(cl, ".git", "objects"))
        with self.assertRaises(rm_mod.Refused):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertTrue(os.path.isdir(cl))

    # 2. containment

    def test_contained_via_remote_tag_when_head_tip_missing(self):
        cl = self.clone(self.url, "ws-tagged")
        self.advance_network(tag_current=True)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "A", co.reasons)

    def test_missing_remote_tip_is_unknown_not_unpushed(self):
        cl = self.clone(self.url, "ws-behind")
        self.advance_network()  # remote main moves to a commit no local repo has
        sh("git", "commit", "-q", "--allow-empty", "-m", "local", cwd=cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C", co.reasons)
        self.assertEqual(co.missing_tips, 1)
        self.assertTrue(any("containment unknown" in r for r in co.reasons), co.reasons)

    def test_missing_tip_found_in_sibling_repo(self):
        cl = self.clone(self.url, "ws-behind")
        sh("git", "commit", "-q", "--allow-empty", "-m", "will be pushed via elsewhere", cwd=cl)
        sh("git", "push", "-q", self.url, "HEAD:refs/heads/tmp", cwd=cl)
        sh("git", "-C", self.main, "fetch", "-q")
        sh("git", "-C", self.main, "merge", "-q", "--ff-only", "origin/tmp")
        self.commit(self.main, name="later.txt", msg="later on main")
        sh("git", "-C", self.main, "push", "-q", "origin", "main")
        sh("git", "push", "-q", self.url, "--delete", "tmp", cwd=cl)
        # network main now holds cl's commit only as an ancestor of a tip that
        # exists locally in the main checkout alone
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "A", co.reasons)

    # 3. read-only checkout

    def test_read_only_clone_is_not_partially_deleted(self):
        cl = self.clone(self.url, "ws-ro")
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "A")
        sh("chmod", "-R", "a-w", cl)
        self.addCleanup(sh, "chmod", "-R", "u+w", cl)
        with self.assertRaisesRegex(rm_mod.Refused, "not writable"):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertTrue(os.path.isfile(os.path.join(cl, "README.md")))
        self.assertEqual(sh("git", "status", "--porcelain", cwd=cl), "")

    def test_read_only_clone_is_C_in_inventory(self):
        cl = self.clone(self.url, "ws-ro")
        sh("chmod", "-R", "a-w", cl)
        self.addCleanup(sh, "chmod", "-R", "u+w", cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C")
        self.assertTrue(co.reasons[0].startswith("cannot be deleted safely"), co.reasons)


class TestPruneScope(GitFixture):
    def test_keep_listed_owner_is_never_pruned(self):
        url = self.network_repo()
        owner = self.clone(url, "ws-restricted")
        wt = self.worktree(owner, "ws-child", "child")
        gone = self.worktree(owner, "ws-gone", "gone")
        shutil.rmtree(gone)
        self.cli("--apply", "--keep", os.path.dirname(owner))
        self.assertIn("ws-gone", sh("git", "worktree", "list", cwd=owner))
        self.assertTrue(os.path.isdir(owner))
        self.assertTrue(os.path.isdir(wt))  # its owner is keep-listed


class TestReviewRound1(GitFixture):
    """Guard gaps found in the first independent review."""

    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def _a(self, path, **kw):
        co = self.by_path(self.build(**kw))[path]
        self.assertEqual(co.cls, "A", co.reasons)
        return co

    def _refused(self, co, pattern):
        with self.assertRaisesRegex(rm_mod.Refused, pattern):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertTrue(os.path.isdir(co.path))

    def test_ignored_data_created_after_inventory(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._a(cl)
        self.write(cl, "db.sqlite3", "precious")
        self._refused(co, "not regenerable")

    def test_assume_unchanged_hides_edit(self):
        cl = self.clone(self.url, "ws-cl")
        sh("git", "update-index", "--assume-unchanged", "README.md", cwd=cl)
        self.write(cl, "README.md", "edited\n")
        self.assertEqual(sh("git", "status", "--porcelain", cwd=cl), "")
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C")
        self.assertIn("assume-unchanged", co.reasons[0])

    def test_skip_worktree_set_after_inventory(self):
        wt = self.worktree(self.main, "ws-a", "a")
        co = self._a(wt)
        sh("git", "update-index", "--skip-worktree", "README.md", cwd=wt)
        self.write(wt, "README.md", "edited\n")
        self._refused(co, "skip-worktree")

    def test_submodule_is_C(self):
        sub_url = self.network_repo("sub")
        cl = self.clone(self.url, "ws-super")
        sh("git", "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub_url, "sub",
           cwd=cl)
        sh("git", "commit", "-qm", "add sub", cwd=cl)
        sh("git", "push", "-q", "origin", "main", cwd=cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C")
        self.assertTrue(any("submodule" in r for r in co.reasons), co.reasons)

    def test_replace_ref_does_not_fake_containment(self):
        cl = self.clone(self.url, "ws-cl")
        tip = sh("git", "rev-parse", "origin/main", cwd=cl).strip()
        self.commit(cl, msg="unpushed")
        # replace the remote tip with a commit whose parent is the unpushed one
        tree = sh("git", "rev-parse", "HEAD^{tree}", cwd=cl).strip()
        fake = sh("git", "commit-tree", "-p", "HEAD", "-m", "fake", tree, cwd=cl).strip()
        sh("git", "replace", "-f", tip, fake, cwd=cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "B", co.reasons)

    def test_grafts_is_C(self):
        cl = self.clone(self.url, "ws-cl")
        self.write(cl, ".git/info/grafts", "")
        self.assertEqual(self.by_path(self.build())[cl].cls, "C")

    def test_unreadable_payload_dir_blocks(self):
        cl = self.clone(self.url, "ws-cl")
        self.write(cl, ".venv/lib/x.py", "x")
        os.chmod(os.path.join(cl, ".venv"), 0)
        self.addCleanup(os.chmod, os.path.join(cl, ".venv"), 0o755)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C", co.reasons)
        self.assertTrue(os.path.isfile(os.path.join(cl, "README.md")))

    def test_unreadable_payload_after_inventory(self):
        cl = self.clone(self.url, "ws-cl")
        self.write(cl, ".venv/lib/x.py", "x")
        co = self._a(cl)
        os.chmod(os.path.join(cl, ".venv"), 0)
        self.addCleanup(os.chmod, os.path.join(cl, ".venv"), 0o755)
        self._refused(co, "cannot read|not writable")
        self.assertTrue(os.path.isdir(os.path.join(cl, ".git")))

    def test_device_backup_inside_payload_dir(self):
        cl = self.clone(self.url, "ws-cl")
        self.write(cl, ".venv/deep/er/still/device-preservation-x/state", "x")
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C", co.reasons)

    def test_bare_shared_borrower_protects_lender(self):
        lender = self.clone(self.url, "ws-lender")
        bare = os.path.join(self.ws, "ws-bare", "proj.git")
        sh("git", "clone", "-q", "--bare", "--shared", lender, bare)
        co = self.by_path(self.build())[lender]
        self.assertEqual(co.cls, "D", co.reasons)

    def test_nested_borrower_in_main_checkout_protects_lender(self):
        lender = self.clone(self.url, "ws-lender")
        nested = os.path.join(self.main, "vendor", "copy")
        sh("git", "clone", "-q", "--shared", lender, nested)
        self.assertEqual(self.by_path(self.build())[lender].cls, "D")

    def test_unreadable_alternates_file_fails_closed(self):
        lender = self.clone(self.url, "ws-lender")
        other = os.path.join(self.projects, "other")
        sh("git", "clone", "-q", "--shared", self.main, other)
        alt = os.path.join(other, ".git", "objects", "info", "alternates")
        os.chmod(alt, 0)
        self.addCleanup(os.chmod, alt, 0o644)
        co = self.by_path(self.build())[lender]
        self.assertEqual(co.cls, "C", co.reasons)

    def test_unreadable_alternates_after_inventory(self):
        lender = self.clone(self.url, "ws-lender")
        co = self._a(lender)
        other = os.path.join(self.projects, "other")
        sh("git", "clone", "-q", "--shared", self.main, other)
        alt = os.path.join(other, ".git", "objects", "info", "alternates")
        os.chmod(alt, 0)
        self.addCleanup(os.chmod, alt, 0o644)
        self._refused(co, "who borrows")

    def test_chain_into_keep_listed_repo_is_not_followed(self):
        kept = self.clone(self.url, "ws-kept")
        leaf = self.clone(kept, "ws-leaf")
        co = self.by_path(self.build(keep=[os.path.dirname(kept)]))[leaf]
        self.assertEqual(co.network_remotes, [])
        self.assertEqual(co.cls, "C")

    def test_remote_error_refuses_even_when_contained(self):
        cl = self.clone(self.url, "ws-cl")
        co = self._a(cl)
        sh("git", "remote", "add", "mirror", f"{NET}missing.git", cwd=cl)
        self._refused(co, "remote check failed")


class TestLsof(GitFixture):
    def test_partial_lsof_output_is_an_error(self):
        from unittest import mock
        from workspace_gc import signals
        fake = mock.Mock(returncode=1, stdout="p1\nn/tmp\n")
        with mock.patch.object(signals.subprocess, "run", return_value=fake):
            cwds, st = signals.read_process_cwds()
        self.assertEqual(st.status, "error")
        self.assertIn(os.path.realpath("/tmp"), cwds)


class TestReviewRound2(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def test_borrower_behind_unlistable_directory_fails_closed(self):
        lender = self.clone(self.url, "ws-lender")
        hidden = os.path.join(self.projects, "locked")
        sh("git", "clone", "-q", "--shared", lender, os.path.join(hidden, "copy"))
        os.chmod(hidden, 0)
        self.addCleanup(os.chmod, hidden, 0o755)
        co = self.by_path(self.build())[lender]
        self.assertEqual(co.cls, "C", co.reasons)
        with self.assertRaisesRegex(rm_mod.Refused, "class C"):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [])

    def test_borrower_in_directory_named_worktrees(self):
        lender = self.clone(self.url, "ws-lender")
        sh("git", "clone", "-q", "--shared", lender,
           os.path.join(self.projects, "worktrees", "copy"))
        self.assertEqual(self.by_path(self.build())[lender].cls, "D")

    def test_keep_listed_lender_alternates_are_not_read(self):
        # kept borrows from main; an unkept clone borrows from kept
        kept = os.path.join(self.ws, "ws-kept", "proj")
        sh("git", "clone", "-q", "--shared", self.main, kept)
        borrower = os.path.join(self.ws, "ws-b", "proj")
        sh("git", "clone", "-q", "--shared", kept, borrower)
        alt = os.path.join(kept, ".git", "objects", "info", "alternates")
        os.chmod(alt, 0)  # reading it would fail the lending scan
        self.addCleanup(os.chmod, alt, 0o644)
        candidate = self.clone(self.url, "ws-cand")
        cos = self.by_path(self.build(keep=[os.path.dirname(kept)]))
        self.assertEqual(cos[candidate].cls, "A", cos[candidate].reasons)

    def test_inaccessible_main_root_fails_closed(self):
        lender = self.clone(self.url, "ws-lender")
        locked = os.path.join(self.tmp, "locked")
        mroot = os.path.join(locked, "projects")
        sh("git", "clone", "-q", "--shared", lender, os.path.join(mroot, "copy"))
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        co = self.by_path(self.build(main_roots=[self.projects, mroot]))[lender]
        self.assertEqual(co.cls, "C", co.reasons)

    def test_missing_main_root_is_fine(self):
        lender = self.clone(self.url, "ws-lender")
        co = self.by_path(self.build(main_roots=[os.path.join(self.tmp, "nope")]))[lender]
        self.assertEqual(co.cls, "A", co.reasons)

    def test_transitive_lender_behind_inaccessible_directory(self):
        # candidate <- external intermediate (outside every scanned root) <- borrower
        cand = self.clone(self.url, "ws-cand")
        outside = os.path.join(self.tmp, "outside")
        inter = os.path.join(outside, "inter")
        sh("git", "clone", "-q", "--shared", cand, inter)
        sh("git", "clone", "-q", "--shared", inter, os.path.join(self.projects, "borrower"))
        os.chmod(outside, 0)
        self.addCleanup(os.chmod, outside, 0o755)
        co = self.by_path(self.build())[cand]
        self.assertEqual(co.cls, "C", co.reasons)
        with self.assertRaises(rm_mod.Refused):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertTrue(os.path.isdir(cand))


class TestHumanSizes(unittest.TestCase):
    def test_sizes_use_the_largest_fitting_unit(self):
        from workspace_gc import report as rep
        self.assertEqual(rep.human_kb(0), "0K")
        self.assertEqual(rep.human_kb(512), "512K")
        self.assertEqual(rep.human_kb(27 * 1024), "27M")
        self.assertEqual(rep.human_kb(1024 * 1024 + 300 * 1024), "1.3G")
