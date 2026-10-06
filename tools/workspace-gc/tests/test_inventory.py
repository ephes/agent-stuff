import os
import shutil

from tests.helpers import NET, GitFixture, SourceStatus, WorkRef, ok_signals, sh
from workspace_gc import git as git_mod
from workspace_gc import inventory


class TestUrls(GitFixture):
    def test_network_url_detection(self):
        for url in ("git@github.com:ephes/x.git", "ssh://git@code.example:2242/a/b.git",
                    "https://git.example/x.git", "host:path/x.git"):
            self.assertTrue(git_mod.is_network_url(url), url)
        for url in ("/Users/x/projects/p", "file:///tmp/p", "../p", "./p", "~/p", ""):
            self.assertFalse(git_mod.is_network_url(url), url)


class TestClassification(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def test_clean_pushed_worktree_is_A(self):
        wt = self.worktree(self.main, "ws-a", "feat/a")
        co = self.by_path(self.build())[wt]
        self.assertEqual((co.kind, co.cls), ("worktree", "A"), co.reasons)
        self.assertEqual(co.network_remotes, [self.url])
        self.assertEqual(co.unpushed, 0)

    def test_pushed_branch_on_remote_is_A(self):
        wt = self.worktree(self.main, "ws-a", "feat/a")
        self.commit(wt)
        sh("git", "push", "-q", "origin", "feat/a", cwd=wt)
        self.assertEqual(self.by_path(self.build())[wt].cls, "A")

    def test_unpushed_worktree_is_B_with_commits(self):
        wt = self.worktree(self.main, "ws-b", "feat/b")
        self.commit(wt, msg="local only work")
        co = self.by_path(self.build())[wt]
        self.assertEqual(co.cls, "B")
        self.assertEqual(co.unpushed, 1)
        self.assertIn("local only work", co.unpushed_commits[0])

    def test_modified_and_untracked_are_C(self):
        wt1 = self.worktree(self.main, "ws-c1", "c1")
        self.write(wt1, "README.md", "changed\n")
        wt2 = self.worktree(self.main, "ws-c2", "c2")
        self.write(wt2, "new.txt", "new\n")
        cos = self.by_path(self.build())
        self.assertEqual(cos[wt1].cls, "C")
        self.assertEqual(cos[wt1].dirty, 1)
        self.assertEqual(cos[wt2].cls, "C")
        self.assertEqual(cos[wt2].untracked, 1)

    def test_clone_with_stash_is_C(self):
        cl = self.clone(self.url, "ws-stash")
        self.write(cl, "README.md", "stashed\n")
        sh("git", "stash", "-q", cwd=cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual((co.kind, co.cls), ("clone", "C"))
        self.assertIn("1 stash(es)", co.reasons)

    def test_clone_local_branch_unpushed_is_B(self):
        cl = self.clone(self.url, "ws-br")
        sh("git", "checkout", "-q", "-b", "side", cwd=cl)
        self.commit(cl, msg="side work")
        sh("git", "checkout", "-q", "main", cwd=cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertEqual(co.unpushed, 1)

    def test_local_origin_chain_is_followed(self):
        mid = self.clone(self.main, "ws-mid")          # origin = ~/projects/proj (local)
        leaf = self.clone(mid, "ws-leaf")              # origin = ws-mid/proj (local)
        cos = self.by_path(self.build())
        self.assertEqual(cos[leaf].network_remotes, [self.url])
        self.assertEqual(cos[leaf].cls, "A", cos[leaf].reasons)
        self.assertIn(f"local remote of {leaf}", cos[mid].notes)

    def test_commit_only_in_local_origin_is_not_pushed(self):
        mid = self.clone(self.main, "ws-mid")
        self.commit(mid, msg="mid only")
        leaf = self.clone(mid, "ws-leaf")
        cos = self.by_path(self.build())
        self.assertEqual(cos[leaf].cls, "B")
        self.assertEqual(cos[mid].cls, "B")

    def test_tip_object_only_in_chain_repo_counts_via_alternates(self):
        # leaf holds X; the network only has Y (child of X), whose object
        # exists only in the local origin ws-mid.
        mid = self.clone(self.main, "ws-mid")
        self.commit(mid, msg="X")
        leaf = self.clone(mid, "ws-leaf")
        self.commit(mid, name="y.txt", msg="Y")
        sh("git", "push", "-q", self.url, "HEAD:refs/heads/later", cwd=mid)
        cos = self.by_path(self.build())
        self.assertEqual(cos[leaf].cls, "A", cos[leaf].reasons)
        self.assertEqual(cos[mid].cls, "A", cos[mid].reasons)

    def test_origin_less_clone_resolved_by_root_commit(self):
        cl = self.clone(self.main, "ws-orphan")
        sh("git", "remote", "remove", "origin", cwd=cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.network_remotes, [self.url])
        self.assertEqual(co.cls, "A", co.reasons)

    def test_no_network_remote_is_C(self):
        repo = os.path.join(self.ws, "ws-local", "solo")
        os.makedirs(repo)
        sh("git", "init", "-q", repo)
        self.commit(repo)
        co = self.by_path(self.build())[repo]
        self.assertEqual(co.cls, "C")
        self.assertIn("no network remote found", co.reasons)

    def test_unreachable_remote_is_C(self):
        cl = self.clone(self.url, "ws-unreach")
        sh("git", "remote", "set-url", "origin", f"{NET}missing.git", cwd=cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C")
        self.assertTrue(any("unreachable" in r for r in co.reasons), co.reasons)

    def test_unreachable_second_remote_with_unpushed_is_C_not_B(self):
        cl = self.clone(self.url, "ws-two")
        sh("git", "remote", "add", "mirror", f"{NET}missing.git", cwd=cl)
        self.commit(cl)
        self.assertEqual(self.by_path(self.build())[cl].cls, "C")

    def test_device_backups_are_C(self):
        wt = self.worktree(self.main, "ws-dev", "dev")
        self.write(wt, ".cache/device-db-backups/20261005T1/db.sqlite", "x")
        wt2 = self.worktree(self.main, "ws-dev2", "dev2")
        self.write(wt2, ".cache/device-preservation-abc-20261005/state", "x")
        cos = self.by_path(self.build())
        self.assertEqual(cos[wt].cls, "C")
        self.assertEqual(cos[wt2].cls, "C")
        self.assertTrue(cos[wt2].device_backups)

    def test_ignored_unique_data_is_C_and_payload_is_not(self):
        wt = self.worktree(self.main, "ws-db", "db")
        self.write(wt, "db.sqlite3", "data")
        wt2 = self.worktree(self.main, "ws-venv", "venv")
        self.write(wt2, ".venv/lib/x.py", "x")
        cos = self.by_path(self.build(sizes=True))
        self.assertEqual(cos[wt].cls, "C")
        self.assertEqual(cos[wt].ignored_unique, ["db.sqlite3"])
        self.assertEqual(cos[wt2].cls, "A", cos[wt2].reasons)
        self.assertEqual([p["path"] for p in cos[wt2].payloads], [".venv"])
        self.assertGreater(cos[wt2].size_kb, 0)

    def test_extra_regenerable_name(self):
        wt = self.worktree(self.main, "ws-db", "db")
        self.write(wt, "db.sqlite3", "data")
        self.assertEqual(self.by_path(self.build(regenerable=["db.sqlite3"]))[wt].cls, "A")

    def test_keep_list_is_C_and_not_inspected(self):
        broken = os.path.join(self.ws, "ws-restricted", "repo")
        os.makedirs(broken)
        self.write(broken, ".git", "gitdir: /nonexistent\n")
        keep = os.path.join(self.ws, "ws-restricted")
        co = self.by_path(self.build(keep=[keep]))[broken]
        self.assertEqual(co.cls, "C")
        self.assertTrue(co.keep_listed)
        self.assertEqual(co.error, "")
        self.assertEqual(co.kind, "unknown")

    def test_keep_file_and_glob(self):
        wt = self.worktree(self.main, "ws-keepme", "k")
        kf = os.path.join(self.tmp, "keep")
        with open(kf, "w") as fh:
            fh.write("# comment\n" + os.path.join(self.ws, "ws-keep*") + "\n")
        self.assertEqual(self.by_path(self.build(keep_file=kf))[wt].cls, "C")

    def test_builtin_keep_contains_echoport(self):
        self.assertIn(os.path.expanduser("~/workspaces/ws-echoport-retention-race"),
                      inventory.load_keep_patterns([], None))

    def test_herdr_pane_in_workspace_is_D(self):
        wt = self.worktree(self.main, "ws-busy", "busy")
        other = os.path.join(self.ws, "ws-busy", "notes")
        os.makedirs(other)
        co = self.by_path(self.build(ok_signals(herdr_cwds=[other])))[wt]
        self.assertEqual(co.cls, "D")

    def test_process_cwd_inside_is_D_and_sibling_workspace_is_not(self):
        wt = self.worktree(self.main, "ws-busy", "busy")
        wt2 = self.worktree(self.main, "ws-busy2", "busy2")
        cos = self.by_path(self.build(ok_signals(process_cwds=[os.path.join(wt, "sub")])))
        self.assertEqual(cos[wt].cls, "D")
        self.assertEqual(cos[wt2].cls, "A")

    def test_work_item_active_is_D_closed_is_note(self):
        wt = self.worktree(self.main, "ws-item", "item")
        wt2 = self.worktree(self.main, "ws-closed", "closed")
        sig = ok_signals(work_refs=[WorkRef("x", "implementing", os.path.join(self.ws, "ws-item")),
                                    WorkRef("y", "merged", wt2)])
        cos = self.by_path(self.build(sig))
        self.assertEqual(cos[wt].cls, "D")
        self.assertIn("active work item: x", cos[wt].reasons)
        self.assertEqual(cos[wt2].cls, "A")
        self.assertTrue(any("closed work item y" in n for n in cos[wt2].notes))

    def test_clone_owning_worktree_is_D(self):
        cl = self.clone(self.url, "ws-owner")
        wt = self.worktree(cl, "ws-child", "child")
        cos = self.by_path(self.build())
        self.assertEqual(cos[cl].cls, "D")
        self.assertEqual(cos[wt].cls, "A")

    def test_main_root_overlap_is_D(self):
        from workspace_gc import inventory as inv
        result = inv.build([self.projects], ok_signals(), main_roots=[self.projects],
                           keep_file=None, sizes=False)
        self.assertEqual([c.cls for c in result.checkouts], ["D"])

    def test_symlink_out_of_root_is_not_followed(self):
        os.makedirs(os.path.join(self.ws, "ws-link"))
        os.symlink(self.main, os.path.join(self.ws, "ws-link", "proj"))
        os.symlink(self.projects, os.path.join(self.ws, "ws-dirlink"))
        self.assertEqual(self.build().checkouts, [])

    def test_recently_active_is_D(self):
        wt = self.worktree(self.main, "ws-new", "new")
        co = self.by_path(self.build(min_idle_hours=48))[wt]
        self.assertEqual(co.cls, "D")
        self.assertTrue(any("recently active" in r for r in co.reasons))

    def test_broken_checkout_is_C(self):
        wt = self.worktree(self.main, "ws-broken", "broken")
        shutil.rmtree(os.path.join(self.main, ".git", "worktrees"))
        co = self.by_path(self.build())[wt]
        self.assertEqual(co.cls, "C")
        self.assertTrue(co.reasons[0].startswith("not inspectable"))

    def test_status_does_not_write_index(self):
        wt = self.worktree(self.main, "ws-idx", "idx")
        gdir = sh("git", "rev-parse", "--path-format=absolute", "--git-dir", cwd=wt).strip()
        index = os.path.join(gdir, "index")
        os.utime(os.path.join(wt, "README.md"))  # stat change git would refresh
        before = os.stat(index).st_mtime_ns
        self.build()
        self.assertEqual(os.stat(index).st_mtime_ns, before)

    def test_signal_errors_block_apply(self):
        sig = ok_signals()
        sig.status["herdr"] = SourceStatus("error", "boom")
        sig.status["work"] = SourceStatus("absent")
        self.assertEqual(sig.apply_blockers(), ["herdr: error (boom)"])
