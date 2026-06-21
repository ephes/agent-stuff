import os
import subprocess
import tempfile
import unittest
from pi_review_loop import bundle


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


class TestBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print('one')\n")
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, **kw):
        out = os.path.join(self.repo, "review-bundle.md")
        defaults = dict(max_file_size=262144, max_diff_bytes_per_file=262144,
                        max_bundle_bytes=2097152)
        defaults.update(kw)
        return bundle.build_bundle(self.repo, out, **defaults)

    def test_includes_unstaged_diff(self):
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print('two')\n")
        res = self._build()
        with open(res.path) as fh:
            text = fh.read()
        self.assertIn("two", text)
        self.assertIn("diffstat", text.lower())
        self.assertTrue(res.has_changes)

    def test_clean_worktree_reports_no_changes(self):
        res = self._build()
        self.assertFalse(res.has_changes)

    def test_untracked_file_contents_included(self):
        with open(os.path.join(self.repo, "new.py"), "w") as fh:
            fh.write("NEW_MARKER = 1\n")
        res = self._build()
        with open(res.path) as fh:
            self.assertIn("NEW_MARKER", fh.read())
        self.assertTrue(res.has_changes)

    def test_untracked_file_in_directory_included(self):
        os.mkdir(os.path.join(self.repo, "newdir"))
        with open(os.path.join(self.repo, "newdir", "new.py"), "w") as fh:
            fh.write("NESTED_MARKER = 1\n")
        res = self._build()
        with open(res.path) as fh:
            self.assertIn("NESTED_MARKER", fh.read())

    def test_oversized_file_is_skipped_not_inlined(self):
        big = "x" * 5000
        with open(os.path.join(self.repo, "big.txt"), "w") as fh:
            fh.write(big + "\n")
        res = self._build(max_file_size=1000)
        self.assertTrue(any(s["path"] == "big.txt" for s in res.skipped_files))
        with open(res.path) as fh:
            self.assertNotIn(big, fh.read())

    def test_per_file_diff_truncated(self):
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("\n".join(f"line{i}" for i in range(2000)) + "\n")
        res = self._build(max_diff_bytes_per_file=500)
        self.assertTrue(res.truncations)

    def test_untracked_file_with_space_in_name_included(self):
        with open(os.path.join(self.repo, "with space.py"), "w") as fh:
            fh.write("SPACED_MARKER = 1\n")
        res = self._build()
        with open(res.path) as fh:
            self.assertIn("SPACED_MARKER", fh.read())

    def test_staged_diff_included(self):
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print('staged change')\n")
        git(self.repo, "add", "a.py")
        res = self._build()
        with open(res.path) as fh:
            text = fh.read()
        self.assertIn("staged change", text)
        self.assertIn("Staged diff", text)

    def test_whole_bundle_cap_drops_low_priority_section(self):
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print('changed')\n")
        with open(os.path.join(self.repo, "extra.py"), "w") as fh:
            fh.write("X = 1\n" * 200)
        res = self._build(max_bundle_bytes=200)
        self.assertTrue(any(t.get("dropped") for t in res.truncations))

    def test_untracked_binary_recorded_in_skipped(self):
        with open(os.path.join(self.repo, "blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01\x02BIN\x00")
        res = self._build()
        self.assertTrue(any(s["path"] == "blob.bin" and s["reason"] == "binary"
                            for s in res.skipped_files))

    def test_per_file_truncation_records_path_with_spaces(self):
        fname = "with space.py"
        with open(os.path.join(self.repo, fname), "w") as fh:
            fh.write("\n".join(f"line{i}" for i in range(2000)) + "\n")
        git(self.repo, "add", fname)
        res = self._build(max_diff_bytes_per_file=400)
        paths = [t.get("path") for t in res.truncations]
        self.assertIn(fname, paths, paths)

    def test_per_file_diff_truncation_keeps_other_files(self):
        # two changed tracked files; cap small enough to truncate the big one
        # but keep the small one fully.
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("\n".join(f"line{i}" for i in range(2000)) + "\n")
        with open(os.path.join(self.repo, "small.py"), "w") as fh:
            fh.write("SMALL_MARKER = 1\n")
        git(self.repo, "add", "small.py")  # make small.py a tracked change too
        res = self._build(max_diff_bytes_per_file=600)
        with open(res.path) as fh:
            text = fh.read()
        # the small file's content survives even though the big file was truncated
        self.assertIn("SMALL_MARKER", text)
        self.assertTrue(any(t.get("path", "").endswith("a.py") for t in res.truncations))


if __name__ == "__main__":
    unittest.main()
