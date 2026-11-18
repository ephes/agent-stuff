# model-floor: allow-file -- fixtures name pre-6.2 ids to prove they are found.
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import model_floor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


class TestIds(unittest.TestCase):
    def test_old_ids_are_found(self):
        for text, ids in (
            ("run gpt-6.1-sol now", ["gpt-6.1"]),
            ("`gpt-6-sol` and gpt-6-astra", ["gpt-6", "gpt-6"]),
            ("GPT-6 Sol review", ["GPT-6"]),
            ("GPT-6.1 Sol, gpt-5.6-terra, openai/gpt-4o", ["GPT-6.1", "gpt-5.6", "gpt-4"]),
            ("-m gpt-5 -c x", ["gpt-5"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(model_floor.old_ids(text), ids)

    def test_current_and_unnumbered_ids_are_not(self):
        for text in ("gpt-6.2-sol", "gpt-6.2-astra", "GPT-6.2 Sol", "gpt-6.10-sol",
                     "gpt-7-sol", "gpt-9000-turbo", "gpt-daybreak-blue-latest",
                     "codex-auto-review", "chatgpt-6", "my_gpt-5", "gpt-6.2.1"):
            with self.subTest(text=text):
                self.assertEqual(model_floor.old_ids(text), [])

    def test_below_floor(self):
        self.assertTrue(model_floor.below_floor("openai-codex/gpt-6.1-sol"))
        self.assertTrue(model_floor.below_floor("gpt-6-sol"))
        self.assertFalse(model_floor.below_floor("openai-codex/gpt-6.2-sol"))
        self.assertFalse(model_floor.below_floor("gpt-daybreak-blue-latest"))


class TestScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = model_floor.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_reports_active_files_and_skips_history(self):
        self.write("skills/a/SKILL.md", "ok gpt-6.2-sol\nruns `gpt-6.1-sol` at low\n")
        self.write("CHANGELOG.md", "- moved from gpt-6.1-sol\n")
        self.write("tools/x/CHANGELOG.md", "- gpt-5.6-sol\n")
        self.write("docs/archive/old.md", "gpt-5.5\n")
        self.write("docs/plans/p.md", "gpt-5.5\n")
        self.write("docs/specs/s.md", "gpt-5.5\n")
        self.write("docs/review-cycle-log.md", "GPT-6 Sol\n")
        self.write(".git/config", "gpt-5\n")
        found = model_floor.scan(self.root)
        self.assertEqual([(f[0], f[1], f[2]) for f in found],
                         [("skills/a/SKILL.md", 2, "gpt-6.1")])

    def test_markers_and_allow_file(self):
        self.write("t/test_a.py", "x = 'gpt-6-sol'  # model-floor: allow\ny = 'gpt-6-sol'\n")
        self.write("t/test_b.py", "# model-floor: allow-file\nz = 'gpt-5'\n")
        self.write("t/test_c.py", "\n\n\n\n\n# model-floor: allow-file\nz = 'gpt-5'\n")
        self.write("notes/lesson.md", "gpt-6.1-sol was pinned then\n")
        self.write(".model-floor-allow", "# history\nnotes/*.md  # dated lesson\n")
        found = sorted((f[0], f[1]) for f in model_floor.scan(self.root))
        self.assertEqual(found, [("t/test_a.py", 2), ("t/test_c.py", 7)])

    def test_main_exit_codes(self):
        self.write("a.toml", 'model = "gpt-6.2-sol"\n')
        self.assertEqual(self.run_main(self.root)[0], 0)
        self.write("b.toml", 'model = "gpt-6.1-sol"\n')
        rc, out, err = self.run_main(self.root)
        self.assertEqual(rc, 1)
        self.assertIn("b.toml:1: gpt-6.1:", out)
        self.assertIn("1 id(s) below GPT-6.2", err)
        self.assertEqual(self.run_main(self.root, "--allow", "b.toml")[0], 0)
        rc, out, _ = self.run_main(os.path.join(self.root, "b.toml"))
        self.assertEqual(rc, 1)
        self.assertEqual(self.run_main(os.path.join(self.root, "missing"))[0], 2)

    def test_a_git_checkout_scans_only_tracked_and_new_files(self):
        import subprocess
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".gitignore", "scratch/\n")
        self.write("scratch/session.jsonl", "gpt-6.1-sol\n")
        self.write("new.md", "gpt-6-sol\n")
        self.write("kept.md", "gpt-5.6\n")
        subprocess.run(["git", "-C", self.root, "add", "kept.md", ".gitignore"],
                       check=True)
        found = sorted(f[0] for f in model_floor.scan(self.root))
        self.assertEqual(found, ["kept.md", "new.md"])

    def test_binary_files_are_skipped(self):
        with open(os.path.join(self.root, "blob.bin"), "wb") as fh:
            fh.write(b"\0\0gpt-5\0")
        self.assertEqual(model_floor.scan(self.root), [])


class TestRepository(unittest.TestCase):
    """The owner's floor holds in this repository: no id below GPT-6.2 outside
    history. A failure names each file and line to fix."""

    def test_agent_stuff_has_no_id_below_the_floor(self):
        self.assertTrue(os.path.isdir(os.path.join(REPO, "codex", "skills")), REPO)
        found = model_floor.scan(REPO)
        self.assertEqual(found, [], "\n".join(
            f"{rel}:{n}: {m}: {line}" for rel, n, m, line in found))


if __name__ == "__main__":
    unittest.main()
