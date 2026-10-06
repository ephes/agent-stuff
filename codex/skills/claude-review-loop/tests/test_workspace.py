import os
import signal
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from claude_review_loop import workspace


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


class TestReviewCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(base, "src")
        os.mkdir(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        self.write("keep.py", "KEEP = 1\n")
        self.write("gone.py", "GONE = 1\n")
        self.write("staged.py", "STAGED = 1\n")
        self.write(".gitignore", "ignored.txt\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        self.first = git(self.repo, "rev-parse", "HEAD").strip()
        self.write("keep.py", "KEEP = 2\n")
        os.remove(os.path.join(self.repo, "gone.py"))
        self.write("staged.py", "STAGED = 2\n")
        git(self.repo, "add", "staged.py")
        self.write("new/untracked.py", "NEW = 1\n")
        self.write(".env", "TOKEN=abc\n")
        self.write("ignored.txt", "ignored\n")
        self.root = os.path.join(base, "run", "workspace")
        os.mkdir(os.path.dirname(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text, repo=None):
        path = os.path.join(repo or self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def read(self, rel, repo):
        with open(os.path.join(repo, rel)) as fh:
            return fh.read()

    def source_state(self):
        return (git(self.repo, "status", "--porcelain", "--untracked-files=all"),
                git(self.repo, "for-each-ref"),
                git(self.repo, "worktree", "list", "--porcelain"),
                git(self.repo, "stash", "list"))

    def test_copy_matches_the_reviewed_worktree(self):
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        self.assertEqual(self.read("keep.py", copy.path), "KEEP = 2\n")
        self.assertEqual(self.read("staged.py", copy.path), "STAGED = 2\n")
        self.assertEqual(self.read("new/untracked.py", copy.path), "NEW = 1\n")
        self.assertFalse(os.path.exists(os.path.join(copy.path, "gone.py")))
        # The reviewed changes read as uncommitted work on top of HEAD.
        self.assertEqual(git(copy.path, "rev-parse", "HEAD").strip(), self.first)
        status = git(copy.path, "status", "--porcelain", "--untracked-files=all")
        self.assertIn(" M keep.py", status)
        self.assertIn(" D gone.py", status)
        self.assertIn("?? new/untracked.py", status)
        # History is there too.
        self.assertIn("init", git(copy.path, "log", "--oneline"))

    def test_paths_with_leading_and_trailing_blanks_are_copied(self):
        self.write(" lead.py", "LEAD = 1\n")
        self.write("trail.py ", "TRAIL = 1\n")
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        self.assertEqual(self.read(" lead.py", copy.path), "LEAD = 1\n")
        self.assertEqual(self.read("trail.py ", copy.path), "TRAIL = 1\n")

    def test_secret_looking_and_ignored_files_stay_out(self):
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        self.assertFalse(os.path.exists(os.path.join(copy.path, ".env")))
        self.assertFalse(os.path.exists(os.path.join(copy.path, "ignored.txt")))
        self.assertIn(".env", copy.excluded)

    def test_untracked_credential_files_stay_out(self):
        fakes = {
            ".pgpass": "fake-host:5432:db:fake-user:fake-pass\n",
            ".git-credentials": "https://fake-user:fake-pass@example.invalid\n",
            "sops/age/keys.txt": "# fake age identity\n",
            "client.pfx": "fake\n",
        }
        for path, content in fakes.items():
            self.write(path, content)
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        for path in fakes:
            with self.subTest(path):
                self.assertFalse(os.path.exists(os.path.join(copy.path, path)))
                self.assertIn(path, copy.excluded)
        self.assertEqual(self.read("new/untracked.py", copy.path), "NEW = 1\n")

    def test_modified_tracked_secret_keeps_its_committed_version(self):
        self.write("service.key", "key: committed\n")
        git(self.repo, "add", "service.key")
        git(self.repo, "commit", "-qm", "secret")
        self.write("service.key", "key: local-only\n")
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        self.assertEqual(self.read("service.key", copy.path), "key: committed\n")
        self.assertIn("service.key", copy.excluded)

    def test_staged_only_copy_is_the_index(self):
        copy = workspace.create_copy(self.repo, self.root, staged_only=True)
        self.addCleanup(copy.remove)
        self.assertEqual(self.read("staged.py", copy.path), "STAGED = 2\n")
        self.assertEqual(self.read("keep.py", copy.path), "KEEP = 1\n")
        self.assertTrue(os.path.exists(os.path.join(copy.path, "gone.py")))
        self.assertFalse(os.path.exists(
            os.path.join(copy.path, "new", "untracked.py")))

    def test_staged_secret_is_left_at_its_committed_state(self):
        self.write("id_rsa", "PRIVATE\n")
        git(self.repo, "add", "id_rsa")
        copy = workspace.create_copy(self.repo, self.root, staged_only=True)
        self.addCleanup(copy.remove)
        self.assertFalse(os.path.exists(os.path.join(copy.path, "id_rsa")))
        self.assertIn("id_rsa", copy.excluded)

    def test_writes_in_the_copy_never_reach_the_source(self):
        before = self.source_state()
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        self.write("keep.py", "REVIEWER = 1\n", repo=copy.path)
        self.write("scratch.py", "X = 1\n", repo=copy.path)
        git(copy.path, "add", "-A")
        git(copy.path, "-c", "user.email=r@r", "-c", "user.name=r",
            "commit", "-qm", "reviewer commit")
        git(copy.path, "branch", "reviewer-branch")
        git(copy.path, "tag", "reviewer-tag")
        with self.assertRaises(subprocess.CalledProcessError):
            git(copy.path, "push", "origin", "HEAD:refs/heads/pushed")
        self.assertEqual(self.read("keep.py", self.repo), "KEEP = 2\n")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "scratch.py")))
        self.assertEqual(self.source_state(), before)

    def test_copy_is_not_a_worktree_of_the_source(self):
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        listing = git(self.repo, "worktree", "list", "--porcelain")
        self.assertNotIn(copy.path, listing)
        self.assertEqual(listing.count("worktree "), 1)
        self.assertNotIn("remote.origin", git(copy.path, "config", "--list"))

    def test_hooks_do_not_run_while_the_copy_is_built(self):
        marker = os.path.join(self.tmp.name, "hook-ran")
        hook = os.path.join(self.repo, ".git", "hooks", "post-checkout")
        with open(hook, "w") as fh:
            fh.write(f"#!/bin/sh\ntouch {marker}\n")
        os.chmod(hook, 0o755)
        git(self.repo, "config", "core.hooksPath", ".git/hooks")
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(copy.remove)
        self.assertFalse(os.path.exists(marker))

    def test_remove_deletes_everything_even_when_made_read_only(self):
        copy = workspace.create_copy(self.repo, self.root)
        locked = os.path.join(copy.path, "locked")
        os.mkdir(locked)
        self.write("locked/f", "x", repo=copy.path)
        os.chmod(locked, stat.S_IRUSR | stat.S_IXUSR)
        self.assertTrue(copy.remove())
        self.assertFalse(os.path.lexists(self.root))
        self.assertTrue(copy.summary()["removed"])

    @unittest.skipIf(os.geteuid() == 0, "mode 000 does not deny root")
    def test_remove_deletes_a_directory_left_with_mode_000(self):
        copy = workspace.create_copy(self.repo, self.root)
        sealed = os.path.join(copy.path, "sealed")
        os.makedirs(os.path.join(sealed, "inner"))
        self.write("sealed/inner/f", "x", repo=copy.path)
        os.chmod(os.path.join(sealed, "inner"), 0)
        os.chmod(sealed, 0)
        self.assertTrue(copy.remove())
        self.assertFalse(os.path.lexists(self.root))

    @unittest.skipIf(os.geteuid() == 0, "mode 000 does not deny root")
    def test_remove_never_follows_a_link_out_of_the_copy(self):
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(os.path.join(outside, "keep"))
        with open(os.path.join(outside, "keep", "f"), "w") as fh:
            fh.write("keep\n")
        os.chmod(outside, 0o500)
        copy = workspace.create_copy(self.repo, self.root)
        os.symlink(outside, os.path.join(copy.path, "link-dir"))
        os.symlink(os.path.join(outside, "keep", "f"),
                   os.path.join(copy.path, "link-file"))
        os.chmod(copy.path, 0)
        self.assertTrue(copy.remove())
        self.assertFalse(os.path.lexists(self.root))
        self.assertEqual(stat.S_IMODE(os.stat(outside).st_mode), 0o500)
        self.assertTrue(os.path.exists(os.path.join(outside, "keep", "f")))

    def _swap_for_link_during(self, step):
        """Run remove_tree while `step` (an os function the walk calls) swaps
        the sealed directory for a link to an outside directory right after
        the walk checked it - what a process the reviewer left behind could
        do. The outside directory must come through untouched."""
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(os.path.join(outside, "keep"))
        with open(os.path.join(outside, "keep", "f"), "w") as fh:
            fh.write("keep\n")
        os.chmod(os.path.join(outside, "keep"), 0o500)
        os.chmod(outside, 0o500)
        copy = workspace.create_copy(self.repo, self.root)
        sealed = os.path.join(copy.path, "sealed")
        os.mkdir(sealed)
        os.chmod(sealed, 0)
        real = getattr(workspace.os, step)
        swapped = []

        def racing(target, *args, **kwargs):
            out = real(target, *args, **kwargs)
            if os.path.basename(str(target)) == "sealed" and not swapped:
                swapped.append(True)
                os.chmod(sealed, 0o700)
                os.rename(sealed, os.path.join(copy.path, "moved-away"))
                os.symlink(outside, sealed)
            return out
        with mock.patch.object(workspace.os, step, racing):
            removed = workspace.remove_tree(copy.root)
        self.assertTrue(swapped, f"the walk never called os.{step} on the entry")
        self.assertTrue(removed)
        self.assertFalse(os.path.lexists(self.root))
        self.assertEqual(stat.S_IMODE(os.stat(outside).st_mode), 0o500)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(outside, "keep")).st_mode), 0o500)
        self.assertTrue(os.path.exists(os.path.join(outside, "keep", "f")))

    @unittest.skipIf(os.geteuid() == 0, "mode 000 does not deny root")
    def test_a_directory_swapped_for_a_link_after_its_check_is_not_followed(self):
        self._swap_for_link_during("stat")

    @unittest.skipIf(os.geteuid() == 0, "mode 000 does not deny root")
    def test_a_directory_swapped_for_a_link_after_its_chmod_is_not_followed(self):
        self._swap_for_link_during("chmod")

    def test_remove_reports_failure_instead_of_raising(self):
        copy = workspace.create_copy(self.repo, self.root)
        self.addCleanup(workspace.remove_tree, self.root)

        def boom(*_args, **_kwargs):
            raise TypeError("rmtree broke")
        with mock.patch.object(workspace.shutil, "rmtree", boom):
            self.assertFalse(workspace.remove_tree(copy.root))
        self.assertTrue(workspace.remove_tree(copy.root))

    def test_failed_build_leaves_nothing_behind(self):
        empty = os.path.join(self.tmp.name, "empty")
        os.mkdir(empty)
        git(empty, "init", "-q")
        with self.assertRaises(ValueError):
            workspace.create_copy(empty, self.root)
        self.assertFalse(os.path.lexists(self.root))

    def test_existing_root_is_refused(self):
        os.mkdir(self.root)
        with self.assertRaises(FileExistsError):
            workspace.create_copy(self.repo, self.root)

    def test_copy_from_a_linked_worktree(self):
        linked = os.path.join(self.tmp.name, "linked")
        git(self.repo, "worktree", "add", "-q", "--detach", linked, "HEAD")
        self.write("in_linked.py", "L = 1\n", repo=linked)
        copy = workspace.create_copy(linked, self.root)
        self.addCleanup(copy.remove)
        self.assertEqual(self.read("in_linked.py", copy.path), "L = 1\n")
        self.assertEqual(self.read("keep.py", copy.path), "KEEP = 1\n")


class TestTerminateAsInterrupt(unittest.TestCase):
    def test_sigterm_raises_keyboard_interrupt_and_handlers_are_restored(self):
        before = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(KeyboardInterrupt):
            with workspace.terminate_as_interrupt():
                os.kill(os.getpid(), signal.SIGTERM)
                signal.pause() if hasattr(signal, "pause") else None
        self.assertIs(signal.getsignal(signal.SIGTERM), before)


if __name__ == "__main__":
    unittest.main()
