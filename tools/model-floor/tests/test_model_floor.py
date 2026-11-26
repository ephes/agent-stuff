# model-floor: allow-file -- fixtures name pre-6.2 ids to prove they are found.
import errno
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

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

    def test_orders_oversized_version_components(self):
        for version, expected in (
            ("9" * 5000, False),
            ("6." + "9" * 5000, False),
            ("5." + "9" * 5000, True),
            ("０" * 5000 + "６.０１", True),
        ):
            model_id = "gpt-" + version
            with self.subTest(length=len(version), suffix=version[-8:]):
                self.assertEqual(model_floor.below_floor("openai/" + model_id), expected)
                old = "gpt-6.1"
                self.assertEqual(model_floor.old_ids(f"{model_id} {old}"),
                                 [model_id, old] if expected else [old])


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
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".git/notes", "gpt-5\n")
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

    def test_allowlist_is_optional_and_accepts_globs_at_the_limit(self):
        self.write("history/old.md", "gpt-6.1\n")
        self.assertEqual(self.run_main(self.root)[0], 1)
        self.write(".model-floor-allow", "# comment\n\nkeep/*\nhistory/* # old models\n")
        with patch.object(model_floor, "MAX_ALLOW_GLOBS", 2, create=True):
            self.assertEqual(self.run_main(self.root), (0, "", ""))

    def test_invalid_allowlist_reports_incomplete_configuration(self):
        self.write("active.md", "gpt-6.1\n")
        path = os.path.join(self.root, ".model-floor-allow")
        for data, detail in (
            (b"#" * 65_537, "65536 bytes"),
            (b"# invalid UTF-8: \xff\n", "UTF-8"),
            (b"keep/*\nhistory/*\nactive.md\n", "2 globs"),
        ):
            with self.subTest(detail=detail):
                with open(path, "wb") as fh:
                    fh.write(data)
                with patch.object(model_floor, "MAX_ALLOW_GLOBS", 2, create=True):
                    rc, out, err = self.run_main(self.root)
                self.assertEqual((rc, out), (2, ""))
                self.assertIn(".model-floor-allow", err)
                self.assertIn(detail, err)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires a FIFO")
    def test_allowlist_fifo_reports_incomplete_configuration_without_blocking(self):
        os.mkfifo(os.path.join(self.root, ".model-floor-allow"))
        cmd = [sys.executable, os.path.join(REPO, "tools/model-floor/bin/model-floor-check"), self.root]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(".model-floor-allow", result.stderr)
        self.assertIn("regular file", result.stderr)

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

    def test_scan_continues_after_oversized_version(self):
        self.write("a.toml", "model = gpt-6." + "9" * 5000 + "\n")
        self.write("b.toml", "model = gpt-6.1\n")
        rc, out, err = self.run_main(self.root)
        self.assertEqual(rc, 1)
        self.assertIn("b.toml:1: gpt-6.1:", out)
        self.assertIn("1 id(s) below GPT-6.2", err)

    def test_a_git_checkout_scans_only_tracked_and_new_files(self):
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".gitignore", "scratch/\n")
        self.write("scratch/session.jsonl", "gpt-6.1-sol\n")
        self.write("new.md", "gpt-6-sol\n")
        self.write("kept.md", "gpt-5.6\n")
        subprocess.run(["git", "-C", self.root, "add", "kept.md", ".gitignore"],
                       check=True)
        found = sorted(f[0] for f in model_floor.scan(self.root))
        self.assertEqual(found, ["kept.md", "new.md"])

    def test_git_enumeration_errors_are_reported_without_falling_back(self):
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write("would-find.md", "gpt-6.1\n")
        for listing, detail in (
            (subprocess.CompletedProcess([], 128, stdout=b""), "exit 128"),
            (subprocess.TimeoutExpired("git ls-files", 60), "timed out"),
            (FileNotFoundError(errno.ENOENT, "git executable missing"), "git executable missing"),
        ):
            with self.subTest(detail=detail), patch.object(model_floor.subprocess, "run") as run:
                if isinstance(listing, Exception):
                    run.side_effect = listing
                else:
                    run.return_value = listing
                rc, out, err = self.run_main(self.root)
                self.assertEqual((rc, out), (2, ""))
                self.assertIn("git ls-files", err)
                self.assertIn(detail, err)

    def test_git_listing_preserves_undecodable_path_bytes(self):
        name = b"kept-\xff.md"
        try:
            rel = os.fsdecode(name)
        except UnicodeError as exc:
            self.skipTest(f"filesystem decoder cannot represent filename bytes: {exc}")
        self.assertEqual(os.fsencode(rel), name)
        path = os.path.join(self.root, rel)
        os.mkdir(os.path.join(self.root, ".git"))
        listing = subprocess.CompletedProcess([], 0, stdout=name + b"\0")
        with patch.object(model_floor.subprocess, "run", return_value=listing):
            self.assertEqual(model_floor.git_files(self.root), [path])

    def test_diagnostics_escape_surrogate_paths(self):
        target = "missing-\udcff.md"
        rc, _, err = self.run_main(target)
        self.assertEqual(rc, 2)
        self.assertIn(r"missing-\udcff.md", err)

    def test_display_path_keeps_windows_separators(self):
        self.assertEqual(model_floor._display_path("a\\b\n.md"), r"a\\b\n.md")
        with patch.object(model_floor.os, "sep", "\\"):
            self.assertEqual(model_floor._display_path("a\\b\n.md"), r"a\b\n.md")

    def test_git_diagnostics_escape_undecodable_paths(self):
        name = b"kept-\xff.md"
        try:
            rel = os.fsdecode(name)
            self.write(rel, "gpt-6.1\n")
        except UnicodeError as exc:
            self.skipTest(f"filesystem cannot represent filename bytes: {exc}")
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.EINVAL, errno.EILSEQ):
                raise
            self.skipTest(f"cannot create a filename with undecodable bytes: {exc}")
        if name not in os.listdir(os.fsencode(self.root)):
            self.skipTest("filesystem changed the filename bytes")
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(["git", "-C", self.root, "add", "--", rel], check=True)
        self.assertEqual(model_floor.scan(self.root)[0][:3], (rel, 1, "gpt-6.1"))
        rc, out, _ = self.run_main(self.root)
        self.assertEqual(rc, 1)
        self.assertIn(f"{ascii(rel)[1:-1]}:1: gpt-6.1:", out)

    def test_git_diagnostics_escape_line_breaks_in_paths(self):
        rel = "kept\nname.md"
        self.write(rel, "gpt-6.1\n")
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(["git", "-C", self.root, "add", "--", rel], check=True)
        rc, out, _ = self.run_main(self.root)
        self.assertEqual(rc, 1)
        self.assertIn(r"kept\nname.md:1: gpt-6.1:", out)
        self.assertEqual(len(out.splitlines()), 1)

    def test_growing_file_cannot_exceed_the_scan_budget(self):
        self.write("a-growing", "gpt-5\n")
        self.write("b-kept", "gpt-6.1\n")
        growing = os.path.join(self.root, "a-growing")
        getsize, fstat = os.path.getsize, os.fstat
        identity = os.stat(growing)

        def grow():
            with open(growing, "ab") as fh:
                fh.write(b"x" * 32)

        def getsize_then_grow(path):
            size = getsize(path)
            if path == growing:
                grow()
            return size

        def fstat_then_grow(fd):
            info = fstat(fd)
            if os.path.samestat(info, identity):
                grow()
            return info

        with (
            patch.object(model_floor, "MAX_BYTES", 32),
            patch.object(os.path, "getsize", getsize_then_grow),
            patch.object(os, "fstat", fstat_then_grow),
        ):
            self.assertEqual([hit[0] for hit in model_floor.scan(self.root)], ["b-kept"])
        self.assertGreater(getsize(growing), 32)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires a FIFO")
    def test_fallback_scan_skips_fifo_and_continues(self):
        os.mkfifo(os.path.join(self.root, "a-pipe"))
        self.write("b-kept", "gpt-6.1\n")
        cmd = [sys.executable, os.path.join(REPO, "tools/model-floor/bin/model-floor-check"), self.root]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("b-kept:1: gpt-6.1:", result.stdout)

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
