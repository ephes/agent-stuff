"""Exercise the launcher preamble without importing the harness."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


class PythonGateTests(unittest.TestCase):
    def setUp(self):
        self.launcher = next((Path(__file__).resolve().parents[1] / "bin").iterdir())
        source = self.launcher.read_text().split("# Make the skill root")[0]
        # Define the gate, but leave invocation to each test.
        self.scope = {"__file__": str(self.launcher)}
        exec(compile(source.rsplit("ensure_python()", 1)[0], str(self.launcher), "exec"), self.scope)

    def gate(self):
        self.scope["ensure_python"]()

    def test_supported_python_stays(self):
        with mock.patch.object(sys, "version_info", (3, 10)), mock.patch("shutil.which") as which:
            self.gate()
            which.assert_not_called()

    def test_old_python_selects_newest_and_preserves_arguments(self):
        with mock.patch.object(sys, "version_info", (3, 9)), \
             mock.patch.object(sys, "argv", [str(self.launcher), "--help", "with spaces"]), \
             mock.patch("shutil.which", side_effect=lambda name: "/bin/" + name if name in ("python3.13", "python3.12") else None), \
             mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as probe, \
             mock.patch("os.execv", side_effect=RuntimeError("exec")) as execute:
            with self.assertRaisesRegex(RuntimeError, "exec"):
                self.gate()
            execute.assert_called_once_with("/bin/python3.13", ["/bin/python3.13", str(self.launcher), "--help", "with spaces"])
            self.assertEqual(probe.call_args.args[0][0], "/bin/python3.13")

    def test_unusable_candidates_are_skipped(self):
        for failure in (subprocess.CompletedProcess([], 1), OSError("broken"), subprocess.TimeoutExpired("python", 5)):
            with self.subTest(failure=failure), \
                 mock.patch.object(sys, "version_info", (3, 9)), \
                 mock.patch("shutil.which", side_effect=lambda name: "/bin/" + name if name in ("python3.13", "python3.12") else None), \
                 mock.patch("subprocess.run", side_effect=[failure, subprocess.CompletedProcess([], 0)]), \
                 mock.patch("os.execv", side_effect=RuntimeError("exec")) as execute:
                with self.assertRaisesRegex(RuntimeError, "exec"):
                    self.gate()
                self.assertEqual(execute.call_args.args[0], "/bin/python3.12")

    def test_missing_interpreter_is_clear_one_line_error(self):
        with mock.patch.object(sys, "version_info", (3, 9)), mock.patch("shutil.which", return_value=None):
            with self.assertRaises(SystemExit) as error:
                self.gate()
            self.assertIn("requires Python 3.10+", str(error.exception))
            self.assertNotIn("\n", str(error.exception))

    def test_launcher_help(self):
        result = subprocess.run([sys.executable, str(self.launcher), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
