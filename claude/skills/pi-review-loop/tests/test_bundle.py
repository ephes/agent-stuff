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

    def test_untracked_file_contents_included(self):
        with open(os.path.join(self.repo, "new.py"), "w") as fh:
            fh.write("NEW_MARKER = 1\n")
        res = self._build()
        with open(res.path) as fh:
            self.assertIn("NEW_MARKER", fh.read())

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


if __name__ == "__main__":
    unittest.main()
