"""Read-only Go module caches (directories 0555 by design) are made writable
right before a removal, so the delete does not stop half-way; other
read-only directories still block."""

import os
import stat
import time

from tests.helpers import GitFixture, ok_signals, sh
from workspace_gc import husks, readonly
from workspace_gc import remove as rm_mod


def go_cache(base, rel=".cache/go-mod", host="example.com"):
    """A module cache laid out like `go mod download` leaves it: read-only
    module directories with read-only files, plus cache/download."""
    root = os.path.join(base, rel)
    mod = os.path.join(root, host, "m@v1.0.0", "sub")
    os.makedirs(mod)
    os.makedirs(os.path.join(root, "cache", "download", host), exist_ok=True)
    with open(os.path.join(mod, "m.go"), "w") as fh:
        fh.write("package m\n")
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, host, "m@v1.0.0"),
                                                topdown=False):
        for f in filenames:
            os.chmod(os.path.join(dirpath, f), 0o444)
        os.chmod(dirpath, 0o555)
    return root


def unlock_all(path):
    sh("chmod", "-R", "u+w", path)


class TestReadOnlyGoCache(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()            # .gitignore has .cache/
        self.main = self.main_checkout(self.url)

    def _guard(self, path):
        self.addCleanup(lambda: os.path.exists(path) and unlock_all(path))

    def test_clone_with_read_only_go_cache_is_removed(self):
        cl = self.clone(self.url, "ws-go")
        go_cache(cl)
        self._guard(cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "A", co.reasons)
        out = rm_mod.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertIn("removed clone", out)
        self.assertFalse(os.path.exists(cl))

    def test_worktree_with_read_only_go_cache_is_removed(self):
        wt = self.worktree(self.main, "ws-gowt", "gowt")
        go_cache(wt, "go/pkg/mod")
        exclude = os.path.join(self.main, ".git", "info", "exclude")
        with open(exclude, "a") as fh:
            fh.write("go/\n")
        self._guard(wt)
        co = self.by_path(self.build(regenerable=["go/"]))[wt]
        self.assertEqual(co.cls, "A", co.reasons)
        out = rm_mod.remove_checkout(co, [self.ws], [self.projects], [], ["go/"])
        self.assertIn("removed worktree", out)
        self.assertFalse(os.path.exists(wt))

    def test_read_only_directory_outside_a_go_cache_still_blocks(self):
        cl = self.clone(self.url, "ws-ro-other")
        ro = os.path.join(cl, ".cache", "other", "pkg")
        os.makedirs(ro)
        os.chmod(ro, 0o555)
        self._guard(cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C")
        self.assertIn("not writable", co.reasons[0])

    def test_unlock_changes_only_go_cache_directories_and_follows_no_symlinks(self):
        base = os.path.join(self.tmp, "unlock")
        root = go_cache(base)
        outside = os.path.join(self.tmp, "outside-ro")
        os.makedirs(outside)
        os.chmod(outside, 0o555)
        self.addCleanup(os.chmod, outside, 0o755)
        other = os.path.join(base, "other-ro")
        os.makedirs(other)
        os.chmod(other, 0o555)
        self.addCleanup(os.chmod, other, 0o755)
        mod = os.path.join(root, "example.com", "m@v1.0.0")
        os.chmod(mod, 0o755)
        os.symlink(outside, os.path.join(mod, "link"))
        os.chmod(mod, 0o555)
        self._guard(base)
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
        try:
            changed = readonly.unlock(fd)
        finally:
            os.close(fd)
        self.assertEqual(changed, 2)   # m@v1.0.0, sub
        for d in (mod, os.path.join(mod, "sub")):
            self.assertTrue(os.stat(d).st_mode & stat.S_IWUSR, d)
        self.assertFalse(os.stat(outside).st_mode & stat.S_IWUSR)
        self.assertFalse(os.stat(other).st_mode & stat.S_IWUSR)
        # files keep their mode; only directories matter for unlinking
        self.assertFalse(os.stat(os.path.join(mod, "sub", "m.go")).st_mode & stat.S_IWUSR)

    def test_fixable_needs_a_go_cache_layout(self):
        base = os.path.join(self.tmp, "fix")
        root = go_cache(base)
        self._guard(base)
        mod = os.path.join(root, "example.com", "m@v1.0.0")
        self.assertTrue(readonly.fixable(mod, base))
        os.rename(os.path.join(root, "cache", "download"), os.path.join(root, "cache", "dl"))
        self.assertFalse(readonly.fixable(mod, base))

    def test_stale_workspace_directory_with_read_only_go_cache_is_removed(self):
        # Several module hosts, so `cache/` is listed (and would be deleted)
        # both before and after a read-only module directory.
        ws = os.path.join(self.ws, "ws-stale-go")
        self.write(ws, "review.log", "log")
        for host in ("aaa.org", "example.com", "gopkg.in", "zzz.org"):
            go_cache(ws, host=host)
        self._guard(ws)
        sig = ok_signals()
        inv = self.build(signals=sig)
        inv.empty_dirs = []
        orig = husks._now
        husks._now = lambda: time.time() + 100 * 3600
        self.addCleanup(setattr, husks, "_now", orig)
        hs = {h.path: h for h in husks.scan(inv, sig, sizes=False)}
        self.assertTrue(hs[ws].stale)
        husks.remove(list(hs.values()), inv.roots, inv.keep_patterns, sig)
        self.assertTrue(hs[ws].removed, hs[ws].outcome)
        self.assertFalse(os.path.exists(ws))

    def test_known_roots_are_reused(self):
        base = os.path.join(self.tmp, "known")
        root = go_cache(base)
        self._guard(base)
        known = []
        sub = os.path.join(root, "example.com", "m@v1.0.0", "sub")
        self.assertTrue(readonly.fixable(sub, base, known))
        self.assertEqual(known, [root])
        calls = []
        orig = readonly._is_go_root
        readonly._is_go_root = lambda p: calls.append(p) or orig(p)
        self.addCleanup(setattr, readonly, "_is_go_root", orig)
        self.assertTrue(readonly.fixable(os.path.join(root, "example.com", "m@v1.0.0"),
                                         base, known))
        self.assertEqual(calls, [])
        self.assertEqual(known, [root])

    def test_read_only_directory_outside_a_module_still_blocks(self):
        # inside the cache but not below <module>@<version>
        cl = self.clone(self.url, "ws-go-nomod")
        root = go_cache(cl)
        os.chmod(os.path.join(root, "example.com"), 0o555)
        self._guard(cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C")
        self.assertIn("not writable", co.reasons[0])

    def test_checkout_root_with_cache_download_is_not_a_go_cache(self):
        cl = self.clone(self.url, "ws-dl")
        os.makedirs(os.path.join(cl, "cache", "download"))
        ro = os.path.join(cl, ".cache", "x@v1", "pkg")
        os.makedirs(ro)
        os.chmod(ro, 0o555)
        with open(os.path.join(cl, ".git", "info", "exclude"), "a") as fh:
            fh.write("cache/\n")
        self._guard(cl)
        co = self.by_path(self.build())[cl]
        self.assertEqual(co.cls, "C", co.reasons)
        self.assertIn("not writable", co.reasons[0])
        fd = os.open(cl, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(readonly.unlock(fd), 0)
        finally:
            os.close(fd)
        self.assertFalse(os.stat(ro).st_mode & stat.S_IWUSR)

    def test_nested_caches_use_the_outermost_root_on_both_sides(self):
        from workspace_gc import inventory
        top = os.path.join(self.tmp, "nested")
        outer = os.path.join(top, "A")
        os.makedirs(os.path.join(outer, "cache", "download"))
        inner = os.path.join(outer, "cache", "vcs", "B")
        os.makedirs(os.path.join(inner, "cache", "download"))
        mod = os.path.join(inner, "m@v1", "sub")
        os.makedirs(mod)
        os.chmod(mod, 0o555)
        os.chmod(os.path.dirname(mod), 0o555)
        self._guard(top)
        # relative to the outer root the module lies under cache/: not fixable
        unlockable = []
        blockers = inventory.deletion_scan(top, unlockable)
        self.assertTrue(any("not writable" in b for b in blockers), blockers)
        self.assertEqual(unlockable, [])
        fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(readonly.unlock(fd), 0)
        finally:
            os.close(fd)

    def test_scan_and_unlock_agree_on_a_module_with_cache_download_inside(self):
        from workspace_gc import inventory
        top = os.path.join(self.tmp, "testdata")
        root = go_cache(top)
        mod = os.path.join(root, "example.com", "m@v1.0.0")
        os.chmod(mod, 0o755)
        os.makedirs(os.path.join(mod, "testdata", "cache", "download"))
        deep = os.path.join(mod, "testdata", "x@v2")
        os.makedirs(deep)
        os.chmod(deep, 0o555)
        os.chmod(mod, 0o555)
        self._guard(top)
        unlockable = []
        self.assertEqual(inventory.deletion_scan(top, unlockable), [])
        fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY)
        try:
            changed = readonly.unlock(fd)
        finally:
            os.close(fd)
        self.assertEqual(changed, len(unlockable))
        for d in unlockable:
            self.assertTrue(os.stat(d).st_mode & stat.S_IWUSR, d)

    def test_stale_go_cache_is_unlocked_before_anything_is_deleted(self):
        ws = os.path.join(self.ws, "ws-order")
        go_cache(ws, host="gopkg.in")
        self._guard(ws)
        real = husks._empty
        seen = []

        def empty_after_check(fd):
            mod = os.path.join(ws, ".cache", "go-mod", "gopkg.in", "m@v1.0.0")
            seen.append(bool(os.stat(mod).st_mode & stat.S_IWUSR))
            return real(fd)
        husks._empty = empty_after_check
        self.addCleanup(setattr, husks, "_empty", real)
        out = husks._remove_payloads(ws, self.ws, [], whole=True, unlock=True)
        self.assertEqual(out, "")
        self.assertEqual(seen, [True])
        self.assertFalse(os.path.exists(ws))

    def test_husk_inspection_counts_read_only_directories(self):
        ws = os.path.join(self.ws, "ws-count")
        self.write(ws, "a.log", "x")
        self.assertEqual(husks.inspect(ws, sizes=False).readonly_dirs, 0)
        go_cache(ws)
        self._guard(ws)
        self.assertEqual(husks.inspect(ws, sizes=False).readonly_dirs, 2)
