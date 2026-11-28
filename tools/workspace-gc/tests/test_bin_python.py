"""bin/workspace-gc under an interpreter older than 3.11: it runs itself again
under a newer python3.1x, or stops before importing the tool."""

import os
import runpy
import shutil
import sys
import unittest
from unittest import mock

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin",
                   "workspace-gc")
OLD = (3, 9, 6, "final", 0)


class Exec(Exception):
    pass


def fake_execv(path, argv):
    raise Exec(path, argv)


class TestOldPython(unittest.TestCase):
    def run_bin(self, found, env=None):
        which = lambda name: found.get(name)  # noqa: E731
        with mock.patch.object(sys, "version_info", OLD), \
                mock.patch.object(sys, "argv", ["workspace-gc", "remove", "/x"]), \
                mock.patch.object(shutil, "which", which), \
                mock.patch.object(os, "execv", fake_execv), \
                mock.patch.dict(os.environ, env or {}, clear=False):
            if env is None:
                os.environ.pop("WORKSPACE_GC_REEXEC", None)
            # Raises before the tool is imported: Exec (re-run) or SystemExit.
            runpy.run_path(BIN, run_name="not_main")

    def test_reruns_under_newest_found(self):
        found = {"python3.12": "/opt/py/python3.12", "python3.14": "/opt/py/python3.14"}
        with self.assertRaises(Exec) as ctx:
            self.run_bin(found)
        path, argv = ctx.exception.args
        self.assertEqual(path, "/opt/py/python3.14")
        self.assertEqual(argv, ["/opt/py/python3.14", os.path.realpath(BIN), "remove", "/x"])

    def test_finds_a_version_above_3_14(self):
        with self.assertRaises(Exec) as ctx:
            self.run_bin({"python3.15": "/opt/py/python3.15"})
        self.assertEqual(ctx.exception.args[0], "/opt/py/python3.15")

    def test_stops_without_newer_python(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_bin({})
        self.assertIn("needs Python 3.11", str(ctx.exception.code))

    def test_no_second_rerun(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_bin({"python3.14": "/opt/py/python3.14"}, env={"WORKSPACE_GC_REEXEC": "1"})
        self.assertIn("needs Python 3.11", str(ctx.exception.code))


if __name__ == "__main__":
    unittest.main()
