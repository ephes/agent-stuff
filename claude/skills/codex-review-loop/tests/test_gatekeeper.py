import contextlib
import functools
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from codex_review_loop import cli, gatekeeper
from tests.helpers import FAKE, RepoFixture

UNAPPROVED = "0181;6af6bec1;;50AC0E83-DFC5-45F7-BACE-185E114963DF"
APPROVED = "01c1;6af6bec1;;50AC0E83-DFC5-45F7-BACE-185E114963DF"


class TestQuarantineFlags(unittest.TestCase):
    def test_the_values_seen_before_and_after_the_confirmation(self):
        # Homebrew's codex cask, Codex 0.168.0, 2026-11-13.
        self.assertTrue(gatekeeper.is_unapproved(UNAPPROVED))
        self.assertFalse(gatekeeper.is_unapproved(APPROVED))

    def test_only_the_user_approved_flag_decides(self):
        self.assertTrue(gatekeeper.is_unapproved("0081;x;Safari;"))
        self.assertFalse(gatekeeper.is_unapproved("00c1;x;Safari;"))
        self.assertFalse(gatekeeper.is_unapproved("0040"))

    def test_flags_that_do_not_parse_count_as_unapproved(self):
        for value in ("", ";;", "zz;1;2", "0x;"):
            with self.subTest(value=value):
                self.assertTrue(gatekeeper.is_unapproved(value))


class TestCheck(unittest.TestCase):
    def check(self, value=None, *, platform="darwin", error=None):
        def reader(path):
            if error is not None:
                raise error
            return value
        return gatekeeper.check("/opt/x/bin/codex", platform=platform,
                                reader=reader)

    def test_an_unapproved_binary_is_refused_with_the_way_out(self):
        message = self.check(UNAPPROVED)
        self.assertIn("/opt/x/bin/codex", message)
        self.assertIn("'0181'", message)
        self.assertIn("Gatekeeper", message)
        self.assertIn("Codex was not started", message)
        self.assertIn("xattr -d com.apple.quarantine /opt/x/bin/codex", message)
        self.assertNotIn("\n", message)

    def test_the_suggested_command_quotes_the_path(self):
        message = gatekeeper.check("/Applications/My Codex/codex",
                                   platform="darwin", reader=lambda p: UNAPPROVED)
        self.assertIn("xattr -d com.apple.quarantine '/Applications/My Codex/codex'",
                      message)

    def test_an_approved_or_unquarantined_binary_may_run(self):
        self.assertIsNone(self.check(APPROVED))
        self.assertIsNone(self.check(None))

    def test_an_unreadable_attribute_does_not_block(self):
        self.assertIsNone(self.check(error=PermissionError(13, "denied")))

    def test_only_macos_is_checked(self):
        self.assertIsNone(self.check(UNAPPROVED, platform="linux"))


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("xattr"),
                     "reads a real extended attribute on macOS")
class TestReadQuarantine(unittest.TestCase):
    """The reader against the real attribute, written with the system's
    `xattr` on a plain file: nothing is executed, so no dialog can appear."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "codex")
        with open(self.path, "w") as fh:
            fh.write("not a binary\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_the_value_and_follows_a_symlink(self):
        subprocess.run(["xattr", "-w", gatekeeper.QUARANTINE_ATTR, UNAPPROVED,
                        self.path], check=True)
        link = os.path.join(self.tmp.name, "link")
        os.symlink(self.path, link)
        self.assertEqual(gatekeeper.read_quarantine(self.path), UNAPPROVED)
        self.assertEqual(gatekeeper.read_quarantine(link), UNAPPROVED)
        self.assertIsNotNone(gatekeeper.check(link))

    def test_no_attribute_is_none(self):
        self.assertIsNone(gatekeeper.read_quarantine(self.path))
        self.assertIsNone(gatekeeper.check(self.path))

    def test_a_missing_file_raises(self):
        with self.assertRaises(OSError):
            gatekeeper.read_quarantine(os.path.join(self.tmp.name, "absent"))


class _Quota:
    blocked = False
    message = ""


class TestProductionPreflight(unittest.TestCase):
    """The installed path: the native binary is resolved, then checked, before
    any copy is made or Codex is started."""

    def setUp(self):
        self.fx = RepoFixture()
        self.binary = os.path.join(self.fx.root, "native", "codex")
        os.makedirs(os.path.dirname(self.binary))
        with open(self.binary, "w") as fh:
            fh.write(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
        os.chmod(self.binary, 0o755)

    def tearDown(self):
        self.fx.cleanup()

    def run_main(self, value):
        run_dir = os.path.join(self.fx.root, f"run-{time.monotonic_ns()}")
        check = functools.partial(gatekeeper.check, platform="darwin",
                                  reader=lambda path: value)
        env = {"CODEX_REVIEW_HOME": self.fx.home}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli.native_mod, "resolve",
                               return_value=(self.binary, {})), \
                mock.patch.object(cli.gatekeeper_mod, "check", check), \
                mock.patch.dict(os.environ, env), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--repo", self.fx.repo, "--run-dir", run_dir,
                             "--lock-dir", self.fx.lock,
                             "--ledger-dir", self.fx.ledger],
                            quota_check=lambda: _Quota())
        with open(os.path.join(run_dir, "result.json")) as fh:
            return code, json.load(fh), run_dir, err.getvalue()

    def test_an_unapproved_binary_fails_closed_before_codex_starts(self):
        started = time.monotonic()
        code, result, run_dir, err = self.run_main(UNAPPROVED)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, 2)
        self.assertEqual((result["state"], result["failure_kind"]),
                         ("CRASHED", "preflight"))
        self.assertIn("Gatekeeper", result["error"])
        self.assertIn(self.binary, err)
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))
        self.assertFalse(os.path.exists(os.path.join(run_dir, "workspace")))

    def test_an_approved_binary_runs_the_review(self):
        code, result, _, err = self.run_main(APPROVED)
        self.assertEqual((code, result["state"]), (0, "CLEAN"), err)
        self.assertTrue(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))


if __name__ == "__main__":
    unittest.main()
