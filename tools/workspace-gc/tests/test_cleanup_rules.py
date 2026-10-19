"""Regenerable path patterns, empty ignored entries, virtualenvs, resolving
"containment unknown" through a scratch fetch, supersession hints, and
workspace directories without a checkout."""

import json
import os
import shutil

from tests.helpers import GitFixture, WorkRef, ok_signals, sh
from workspace_gc import husks, inventory
from workspace_gc import remove as rm_mod


def exclude(repo, *patterns):
    """Ignore patterns through the repository's info/exclude (shared by its
    worktrees)."""
    common = sh("git", "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=repo).strip()
    with open(os.path.join(common, "info", "exclude"), "a") as fh:
        fh.write("\n".join(patterns) + "\n")


class TestRegenerable(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()   # repository name "proj"
        self.main = self.main_checkout(self.url)
        exclude(self.main, "var/", "out", "tests/", "sub/", "apps/", ".venv311/", ".venv-x/",
                "uv.lock", "notes.txt")

    def cls(self, wt, **kw):
        return self.by_path(self.build(**kw))[wt]

    def test_empty_file_is_regenerable_non_empty_is_not(self):
        wt = self.worktree(self.main, "ws-empty", "empty")
        self.write(wt, "db.sqlite3", "")
        self.assertEqual(self.cls(wt).cls, "A", self.cls(wt).reasons)
        self.write(wt, "db.sqlite3", "data")
        co = self.cls(wt)
        self.assertEqual(co.cls, "C")
        self.assertEqual(co.ignored_unique, ["db.sqlite3"])

    def test_empty_directory_tree_is_regenerable(self):
        wt = self.worktree(self.main, "ws-var", "var")
        os.makedirs(os.path.join(wt, "var", "piper", "x"))
        self.write(wt, "var/piper/empty.txt", "")
        self.assertEqual(self.cls(wt).cls, "A", self.cls(wt).reasons)
        self.write(wt, "var/piper/model.onnx", "weights")
        self.assertEqual(self.cls(wt).cls, "C")

    def test_symlink_is_never_empty(self):
        wt = self.worktree(self.main, "ws-link", "link")
        os.makedirs(os.path.join(wt, "var"))
        os.symlink("/nonexistent", os.path.join(wt, "var", "l"))
        self.assertEqual(self.cls(wt).cls, "C")

    def test_builtin_path_glob_is_anchored(self):
        wt = self.worktree(self.main, "ws-tdb", "tdb")
        self.write(wt, "tests/test_database.sqlite3", "db")
        self.write(wt, "tests/test_database.sqlite3.fingerprint", "f")
        self.write(wt, "uv.lock", "lock")
        self.assertEqual(self.cls(wt).cls, "A", self.cls(wt).reasons)
        self.write(wt, "sub/tests/test_database.sqlite3", "db")
        self.write(wt, "sub/uv.lock", "lock")
        co = self.cls(wt)
        self.assertEqual(co.cls, "C")
        self.assertEqual(co.ignored_unique, ["sub/"])

    def test_extra_path_glob_and_repo_scope(self):
        wt = self.worktree(self.main, "ws-apps", "apps")
        self.write(wt, "apps/ios/Rust/lib.a", "bin")
        self.write(wt, "apps/ios/App.xcodeproj/project.pbxproj", "x")
        self.assertEqual(self.cls(wt).cls, "C")
        pats = ["proj:apps/ios/Rust/", "apps/*/*.xcodeproj/"]
        self.assertEqual(self.cls(wt, regenerable=pats).cls, "A")
        other = ["other:apps/ios/Rust/", "apps/*/*.xcodeproj/"]
        self.assertEqual(self.cls(wt, regenerable=other).cls, "C")
        # `*` matches one component only
        self.assertEqual(self.cls(wt, regenerable=["apps/*"]).cls, "A")
        self.assertEqual(self.cls(wt, regenerable=["*/Rust/", "*/*.xcodeproj/"]).cls, "C")

    def test_pathspec_magic_directory_name_is_checked_on_disk(self):
        wt = self.worktree(self.main, "ws-magic", "magic")
        exclude(self.main, ":private/")
        self.write(wt, ":private/secret.txt", "data")
        co = self.cls(wt, regenerable=["nothing/matches/"])
        self.assertEqual(co.cls, "C")
        self.assertEqual(co.ignored_unique, [":private/"])

    def test_nested_git_metadata_blocks_regenerable_directory(self):
        wt = self.worktree(self.main, "ws-nested", "nested")
        self.write(wt, "var/.git/secrets.txt", "data")
        self.write(wt, "var/empty.txt", "")
        self.assertEqual(self.cls(wt).cls, "C")
        self.assertEqual(self.cls(wt, regenerable=["var/*.txt"]).cls, "C")

    def test_symlinked_directory_inside_ignored_directory_is_unique(self):
        wt = self.worktree(self.main, "ws-symdir", "symdir")
        target = os.path.join(self.tmp, "elsewhere")
        os.makedirs(target)
        os.makedirs(os.path.join(wt, "var"))
        os.symlink(target, os.path.join(wt, "var", "link"))
        self.write(wt, "var/empty.txt", "")
        self.assertEqual(self.cls(wt).cls, "C")

    def test_repository_below_a_regenerable_name_inside_ignored_directory(self):
        wt = self.worktree(self.main, "ws-cachedrepo", "cachedrepo")
        repo = os.path.join(wt, "var", ".cache", "repo")
        os.makedirs(repo)
        sh("git", "init", "-q", repo)
        self.commit(repo, msg="unique history")
        self.assertEqual(self.cls(wt).cls, "C")

    def test_repository_inside_pattern_matched_directory(self):
        wt = self.worktree(self.main, "ws-patrepo", "patrepo")
        repo = os.path.join(wt, "apps", "gen", "repo")
        os.makedirs(repo)
        sh("git", "init", "-q", repo)
        self.commit(repo, msg="unique history")
        self.assertEqual(self.cls(wt, regenerable=["apps/gen/"]).cls, "C")
        self.assertEqual(self.cls(wt, regenerable=["apps"]).cls, "C")

    def test_deeper_pattern_inside_wholly_ignored_directory(self):
        wt = self.worktree(self.main, "ws-deep", "deep")
        self.write(wt, "apps/gen/out.swift", "generated")
        self.write(wt, "apps/gen/sub/more.swift", "generated")
        self.assertEqual(self.cls(wt, regenerable=["apps/gen/"]).cls, "A")
        self.write(wt, "apps/notes.md", "mine")
        self.assertEqual(self.cls(wt, regenerable=["apps/gen/"]).cls, "C")

    def test_trailing_slash_matches_directories_only(self):
        wt = self.worktree(self.main, "ws-out", "out")
        self.write(wt, "out", "a file, not a directory")
        self.assertEqual(self.cls(wt, regenerable=["/out/"]).cls, "C")
        self.assertEqual(self.cls(wt, regenerable=["/out"]).cls, "A")

    def test_name_pattern_still_matches_any_component(self):
        wt = self.worktree(self.main, "ws-name", "name")
        self.write(wt, "sub/deep/notes.txt", "x")
        self.assertEqual(self.cls(wt, regenerable=["notes.txt"]).cls, "A")

    def test_virtualenv_is_payload(self):
        wt = self.worktree(self.main, "ws-venv", "venv")
        self.write(wt, ".venv311/pyvenv.cfg", "home = /usr\n")
        self.write(wt, ".venv311/lib/site.py", "x")
        self.write(wt, ".venv311/.gitignore", "*\n")
        co = self.cls(wt)
        self.assertEqual(co.cls, "A", co.reasons)
        self.assertEqual([p["path"] for p in co.payloads], [".venv311"])

    def test_dir_named_like_a_venv_without_pyvenv_cfg_is_unique(self):
        wt = self.worktree(self.main, "ws-novenv", "novenv")
        self.write(wt, ".venv-x/data.json", "{}")
        self.assertEqual(self.cls(wt).cls, "C")

    def test_regenerable_file_and_removal_recheck(self):
        wt = self.worktree(self.main, "ws-file", "file")
        self.write(wt, "apps/gen/out.swift", "generated")
        rfile = os.path.join(self.tmp, "regenerable")
        with open(rfile, "w") as fh:
            fh.write("# generated\nproj:apps/gen/\n")
        code, out = self.cli("remove", wt)
        self.assertEqual(code, 1, out)
        code, out = self.cli("remove", "--apply", "--regenerable-file", rfile, wt)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(wt))

    def test_recheck_refuses_entry_that_gained_content(self):
        wt = self.worktree(self.main, "ws-late", "late")
        self.write(wt, "db.sqlite3", "")
        co = self.cls(wt)
        self.assertEqual(co.cls, "A")
        self.write(wt, "db.sqlite3", "now with data")
        with self.assertRaisesRegex(rm_mod.Refused, "not regenerable"):
            rm_mod.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertTrue(os.path.isdir(wt))


class TestScratchFetch(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def contained_but_tip_missing(self):
        """A clone whose only local commit is on the network inside a branch
        whose newer tip no local repository has."""
        cl = self.clone(self.url, "ws-behind")
        self.commit(cl, name="feat.txt", msg="feature")
        sh("git", "push", "-q", self.url, "HEAD:refs/heads/feat", cwd=cl)
        other = os.path.join(self.tmp, "other")
        sh("git", "clone", "-q", "-b", "feat", self.url, other)
        self.commit(other, name="more.txt", msg="more on feat")
        sh("git", "push", "-q", "origin", "feat", cwd=other)
        shutil.rmtree(other)
        return cl

    @staticmethod
    def snapshot(repo):
        refs = sh("git", "for-each-ref", "--format=%(refname) %(objectname)", cwd=repo)
        objs = sh("git", "count-objects", "-v", cwd=repo)
        return refs, objs, os.path.exists(os.path.join(repo, ".git", "FETCH_HEAD"))

    def test_unknown_without_fetch(self):
        cl = self.contained_but_tip_missing()
        co = self.by_path(self.build(fetch=False))[cl]
        self.assertEqual(co.cls, "C")
        self.assertTrue(any("containment unknown" in r for r in co.reasons), co.reasons)

    def test_fetch_resolves_and_leaves_checkout_untouched(self):
        cl = self.contained_but_tip_missing()
        before = self.snapshot(cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "A", co.reasons)
        self.assertEqual(co.missing_tips, 0)
        self.assertTrue(any("scratch repository" in n for n in co.notes), co.notes)
        self.assertEqual(self.snapshot(cl), before)
        self.assertFalse([a for a in co.alternates if "workspace-gc-fetch-" in a])

    def test_remove_rechecks_with_a_fresh_fetch(self):
        cl = self.contained_but_tip_missing()
        code, out = self.cli("remove", "--apply", cl)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(cl))

    def test_remove_without_fetch_refuses(self):
        cl = self.contained_but_tip_missing()
        code, out = self.cli("remove", "--apply", "--no-fetch", cl)
        self.assertEqual(code, 1, out)
        self.assertIn("containment unknown", out)
        self.assertTrue(os.path.isdir(cl))

    def test_truly_unpushed_after_fetch_is_B(self):
        cl = self.contained_but_tip_missing()
        self.commit(cl, name="local.txt", msg="local only")
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertEqual(co.unpushed, 1)

    def test_unreachable_fetch_stays_unknown(self):
        cl = self.contained_but_tip_missing()
        ins = inventory.Inspector([self.projects])
        orig = ins.fetched_store
        ins.fetched_store = lambda url: ("", "fetch failed")
        co = inventory.Checkout(path=cl, root=self.ws, workspace=os.path.dirname(cl))
        inventory.inspect(co, ins, keep_patterns=[], regenerable=[], sizes=False)
        ins.fetched_store = orig
        inventory.classify(co)
        self.assertEqual(co.cls, "C")
        self.assertTrue(co.missing_tips)


class TestHints(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def test_same_patch_and_subject_on_default_branch(self):
        wt = self.worktree(self.main, "ws-sup", "sup")
        sha = self.commit(wt, name="fix.txt", text="fixed\n", msg="Fix the thing")
        self.commit(wt, name="own.txt", text="mine\n", msg="Only here")
        self.commit(self.main, name="main.txt", msg="Main moves on")
        sh("git", "cherry-pick", sha, cwd=self.main)
        sh("git", "push", "-q", "origin", "main", cwd=self.main)
        co = self.by_path(self.build())[wt]
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertEqual(len(co.unpushed_commits), 2)
        hints = dict(zip([c.split()[0] for c in co.unpushed_commits], co.unpushed_hints))
        self.assertIn("same patch on main", hints[sha[:10]])
        self.assertIn("same subject as main", hints[sha[:10]])
        other = [h for k, h in hints.items() if k != sha[:10]][0]
        self.assertEqual(other, "no match on main")
        code, out = self.cli("remove", wt)
        self.assertIn("same patch on main", out)
        code, out = self.cli()
        self.assertIn("[same patch on main; same subject as main", out)


    def test_merge_commit_is_not_credited_with_a_parents_patch(self):
        sh("git", "checkout", "-q", "-b", "side", cwd=self.main)
        side = self.commit(self.main, name="side.txt", msg="Side change")
        sh("git", "checkout", "-q", "main", cwd=self.main)
        sh("git", "push", "-q", "origin", "main", "side", cwd=self.main)
        wt = self.worktree(self.main, "ws-merge", "merge")
        self.commit(wt, name="own.txt", msg="Own change")
        sh("git", "merge", "-q", "--no-ff", "-m", "Merge side", side, cwd=wt)
        sh("git", "-C", self.main, "push", "-q", "origin", "--delete", "side")
        sh("git", "-C", self.main, "merge", "-q", "side")
        sh("git", "-C", self.main, "push", "-q", "origin", "main")
        co = self.by_path(self.build())[wt]
        hints = dict(zip([c.split()[0] for c in co.unpushed_commits], co.unpushed_hints))
        merge = sh("git", "rev-parse", "HEAD", cwd=wt).strip()[:10]
        self.assertNotIn("same patch", hints[merge])

    def test_hint_failure_does_not_change_the_class(self):
        wt = self.worktree(self.main, "ws-fail", "fail")
        self.commit(wt, msg="Local")
        from workspace_gc.git import GitError
        orig = inventory.Inspector.supersession_hints

        def boom(*a, **k):
            raise GitError("timed out: git cherry")
        inventory.Inspector.supersession_hints = boom
        self.addCleanup(setattr, inventory.Inspector, "supersession_hints", orig)
        co = self.by_path(self.build())[wt]
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertTrue(co.unpushed_hints[0].startswith("hint unavailable"))


class TestHusks(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.main = self.main_checkout(self.url)

    def test_workspace_without_checkout_is_reported(self):
        ws = os.path.join(self.ws, "ws-husk")
        self.write(ws, ".cache/uv/wheel.whl", "x" * 50000)
        self.write(ws, ".cache/prek/hook", "x" * 10000)
        self.write(ws, ".cache/other/keep.txt", "x")
        self.write(ws, "review-r1.log", "log")
        self.worktree(self.main, "ws-live", "live")
        os.makedirs(os.path.join(self.ws, "ws-empty"))
        code, out = self.cli("--json")
        data = json.loads(out)
        hs = {h["path"]: h for h in data["husks"]}
        self.assertEqual(list(hs), [ws])     # not the one with a checkout, not the empty one
        h = hs[ws]
        self.assertEqual(h["files"], 2)   # caches are sized, not walked
        paths = {e["path"]: e["payload"] for e in h["entries"]}
        self.assertEqual(paths, {".cache/uv": True, ".cache/prek": True,
                                 ".cache/other": False, "review-r1.log": False})
        self.assertEqual(h["git_dirs"], [])
        self.assertTrue(os.path.isfile(os.path.join(ws, "review-r1.log")))  # report only

    def test_sizes_and_text(self):
        ws = os.path.join(self.ws, "ws-husk")
        self.write(ws, ".cache/uv/wheel.whl", "x" * 50000)
        self.write(ws, "codex.log", "log")
        inv = self.build()
        inv.empty_dirs = []
        hs = husks.scan(inv, ok_signals(), sizes=True)
        self.assertEqual(len(hs), 1)
        self.assertGreater(hs[0].payload_kb, 0)
        self.assertGreaterEqual(hs[0].kb, hs[0].payload_kb)
        code, out = self.cli()
        self.assertIn("## Workspace directories without a checkout (1,", out)
        self.assertIn(".cache/uv", out)

    def test_deep_repository_and_in_use_are_flagged(self):
        deep = os.path.join(self.ws, "ws-deep", "a", "b", "c")
        os.makedirs(deep)
        sh("git", "init", "-q", deep)
        busy = os.path.join(self.ws, "ws-busy")
        self.write(busy, "notes.md", "x")
        sig = ok_signals(process_cwds=[busy])
        inv = self.build(signals=sig)
        hs = {h.path: h for h in husks.scan(inv, sig, sizes=False)}
        self.assertEqual(hs[os.path.join(self.ws, "ws-deep")].git_dirs, ["a/b/c"])
        self.assertIn("in use", hs[busy].kept)

    def test_repository_inside_a_cache_is_reported(self):
        ws = os.path.join(self.ws, "ws-cachegit")
        repo = os.path.join(ws, ".cache", "prek", "repo")
        os.makedirs(repo)
        sh("git", "init", "-q", repo)
        inv = self.build()
        hs = {h.path: h for h in husks.scan(inv, ok_signals(), sizes=False)}
        self.assertEqual(hs[ws].git_dirs, [".cache/prek/repo"])
        self.assertEqual(hs[ws].files, 0)

    def _later(self, hours):
        orig = husks._now
        husks._now = lambda: __import__("time").time() + hours * 3600
        self.addCleanup(setattr, husks, "_now", orig)

    def _remove(self, sig=None, keep=(), hours=49):
        sig = sig or ok_signals()
        inv = self.build(signals=sig, keep=list(keep))
        inv.empty_dirs = []
        self._later(hours)
        hs = {h.path: h for h in husks.scan(inv, sig, sizes=True)}
        husks.remove(list(hs.values()), inv.roots, inv.keep_patterns, sig)
        return hs

    def test_stale_husk_with_logs_is_removed_whole_and_audited(self):
        ws = os.path.join(self.ws, "ws-stale")
        self.write(ws, "review.log", "log")
        self.write(ws, ".cache/uv/git-v1/checkouts/x/f", "x")
        os.makedirs(os.path.join(ws, ".cache", "uv", "git-v1", "checkouts", "x", ".git"))
        hs = self._remove(hours=100)
        h = hs[ws]
        self.assertTrue(h.removed, h.outcome)
        self.assertEqual(h.removed_what, "directory")
        self.assertGreater(h.removed_kb, 0)
        self.assertFalse(os.path.exists(ws))

    def test_young_or_guarded_or_git_husk_is_not_removed_whole(self):
        busy =os.path.join(self.ws, "ws-busy3")
        self.write(busy, "a.log", "x")
        kept = os.path.join(self.ws, "ws-kept3")
        self.write(kept, "a.log", "x")
        inside = os.path.join(self.ws, "ws-inside3")
        self.write(inside, "a.log", "x")
        git = os.path.join(self.ws, "ws-git3")
        self.write(git, "a.log", "x")
        os.makedirs(os.path.join(git, "a", "b", "c"))
        sh("git", "init", "-q", os.path.join(git, "a", "b", "c"))
        sig = ok_signals(process_cwds=[busy])
        hs = self._remove(sig=sig, keep=[kept, os.path.join(inside, "a.log")], hours=100)
        for ws in (busy, kept, inside, git):
            self.assertFalse(hs[ws].removed, ws)
            self.assertTrue(os.path.isdir(ws), ws)

    def test_keep_glob_matching_a_file_inside_protects_the_directory(self):
        ws = os.path.join(self.ws, "ws-globkeep")
        self.write(ws, "notes-precious.txt", "x")
        hs = self._remove(keep=[os.path.join(self.ws, "*precious*")], hours=100)
        self.assertFalse(hs[ws].removed)
        self.assertTrue(os.path.exists(os.path.join(ws, "notes-precious.txt")))

    def test_replaced_workspace_directory_is_not_removed(self):
        ws = os.path.join(self.ws, "ws-swap")
        self.write(ws, "a.log", "x")
        wrong = os.stat(ws).st_ino + 1
        out = husks._remove_payloads(ws, self.ws, [], whole=True, ino=wrong)
        self.assertEqual(out, "replaced since the inspection")
        self.assertTrue(os.path.exists(os.path.join(ws, "a.log")))

    def test_audit_size_is_measured_at_removal_even_without_sizes(self):
        ws = os.path.join(self.ws, "ws-nosize")
        self.write(ws, "a.log", "x" * 20000)
        sig = ok_signals()
        inv = self.build(signals=sig)
        inv.empty_dirs = []
        self._later(100)
        hs = husks.scan(inv, sig, sizes=False)
        husks.remove(hs, inv.roots, inv.keep_patterns, sig)
        self.assertTrue(hs[0].removed, hs[0].outcome)
        self.assertGreater(hs[0].removed_kb, 0)

    def test_young_husk_is_not_removed_whole(self):
        young = os.path.join(self.ws, "ws-young2")
        self.write(young, "a.log", "x")
        hs = self._remove(hours=10)
        self.assertFalse(hs[young].stale)
        self.assertTrue(os.path.isdir(young))

    def test_cache_only_idle_husk_loses_its_caches_only(self):
        ws = os.path.join(self.ws, "ws-cache")
        self.write(ws, ".cache/uv/wheel.whl", "x" * 5000)
        self.write(ws, "node_modules/a/b.js", "x")
        hs = self._remove()
        h = hs[ws]
        self.assertTrue(h.cache_only)
        self.assertTrue(h.removed, h.outcome)
        self.assertFalse(os.path.exists(os.path.join(ws, ".cache", "uv")))
        self.assertFalse(os.path.exists(os.path.join(ws, "node_modules")))
        self.assertTrue(os.path.isdir(ws))

    def test_young_cache_husk_is_left(self):
        ws = os.path.join(self.ws, "ws-young")
        self.write(ws, ".cache/uv/wheel.whl", "x" * 5000)
        hs = self._remove(hours=2)
        self.assertTrue(hs[ws].cache_only)
        self.assertFalse(hs[ws].removable)
        self.assertTrue(os.path.isdir(os.path.join(ws, ".cache", "uv")))

    def test_husk_with_other_content_or_guards_is_left(self):
        logs = os.path.join(self.ws, "ws-logs")
        self.write(logs, ".cache/uv/wheel.whl", "x" * 5000)
        self.write(logs, "review.log", "x")
        busy = os.path.join(self.ws, "ws-busy2")
        self.write(busy, ".cache/uv/wheel.whl", "x" * 5000)
        kept = os.path.join(self.ws, "ws-kept2")
        self.write(kept, ".cache/uv/wheel.whl", "x" * 5000)
        deep = os.path.join(self.ws, "ws-deepgit")
        self.write(deep, ".cache/uv/wheel.whl", "x" * 5000)
        os.makedirs(os.path.join(deep, "a", "b", "c"))
        sh("git", "init", "-q", os.path.join(deep, "a", "b", "c"))
        sig = ok_signals(process_cwds=[busy])
        hs = self._remove(sig=sig, keep=[kept])
        for ws in (logs, busy, kept, deep):
            self.assertFalse(hs[ws].removed, ws)
            self.assertTrue(os.path.isdir(os.path.join(ws, ".cache", "uv")), ws)

    def test_keep_entry_inside_and_bare_repository_protect_caches(self):
        a = os.path.join(self.ws, "ws-keepin")
        self.write(a, ".cache/uv/data/f", "x" * 5000)
        b = os.path.join(self.ws, "ws-bare")
        bare = os.path.join(b, ".cache", "uv", "repo.git")
        self.write(b, ".cache/uv/repo.git/HEAD", "ref: refs/heads/main")
        os.makedirs(os.path.join(bare, "objects"))
        os.makedirs(os.path.join(bare, "refs"))
        hs = self._remove(keep=[os.path.join(a, ".cache", "uv", "data")])
        for ws in (a, b):
            self.assertFalse(hs[ws].removed, ws)
            self.assertTrue(os.path.isdir(os.path.join(ws, ".cache", "uv")), ws)

    def test_symlinked_cache_parent_is_not_followed(self):
        ws = os.path.join(self.ws, "ws-link")
        self.write(ws, ".cache/uv/wheel.whl", "x" * 5000)
        outside = os.path.join(self.tmp, "outside")
        self.write(outside, "uv/precious", "x")
        h = husks.Husk(path=ws, removable=True)
        shutil_rmtree = os.path.join(ws, ".cache")
        __import__("shutil").rmtree(shutil_rmtree)
        os.symlink(outside, shutil_rmtree)
        out = husks._remove_payloads(ws, self.ws, [".cache/uv"])
        self.assertTrue(out)
        self.assertTrue(os.path.exists(os.path.join(outside, "uv", "precious")))

    def test_root_swapped_for_a_symlink_is_not_followed(self):
        ws = os.path.join(self.ws, "ws-rootswap")
        self.write(ws, ".cache/uv/wheel.whl", "x" * 5000)
        elsewhere = os.path.join(self.tmp, "elsewhere")
        self.write(elsewhere, "ws-rootswap/.cache/uv/precious", "x")
        moved = self.ws + ".moved"
        os.rename(self.ws, moved)
        os.symlink(elsewhere, self.ws)
        out = husks._remove_payloads(ws, self.ws, [".cache/uv"])
        self.assertTrue(out)
        self.assertTrue(os.path.exists(os.path.join(elsewhere, "ws-rootswap/.cache/uv/precious")))

    def test_unverifiable_root_path_removes_nothing(self):
        ws = os.path.join(self.ws, "ws-unverified")
        self.write(ws, ".cache/uv/wheel.whl", "x" * 5000)
        orig = husks._fd_path
        husks._fd_path = lambda fd: None
        self.addCleanup(setattr, husks, "_fd_path", orig)
        self.assertTrue(husks._remove_payloads(ws, self.ws, [".cache/uv"]))
        self.assertTrue(os.path.isdir(os.path.join(ws, ".cache", "uv")))

    def test_keep_listed_and_active_item(self):
        kept = os.path.join(self.ws, "ws-kept")
        self.write(kept, "x.log", "x")
        item = os.path.join(self.ws, "ws-item")
        self.write(item, "x.log", "x")
        sig = ok_signals(work_refs=[WorkRef("slug", "implementing", os.path.join(item, "repo"))])
        inv = self.build(signals=sig, keep=[kept])
        hs = {h.path: h for h in husks.scan(inv, sig, sizes=False)}
        self.assertEqual(hs[kept].kept, "keep-listed")
        self.assertEqual(hs[kept].files, 0)          # not inspected
        self.assertEqual(hs[item].kept, "active work item: slug")
