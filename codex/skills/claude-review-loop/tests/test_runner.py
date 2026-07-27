import os
import signal
import sys
import tempfile
import unittest
from unittest import mock
from claude_review_loop import runner
from claude_review_loop.states import CLEAN, ISSUES, INVALID, CRASHED, STALLED, PROVIDER_ERROR

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py")]


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, mode, **kw):
        defaults = dict(stall_timeout=2, retry_grace=1, global_deadline=30,
                        poll_interval=0.05, model="fake/model")
        defaults.update(kw)
        return runner.run_review(cmd=FAKE + [mode], run_dir=self.run_dir, **defaults)

    def test_clean(self):
        r = self._run("clean")
        self.assertEqual(r.state, CLEAN)
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "result.json")))
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "events.jsonl")))

    def test_issues_items_parsed(self):
        r = self._run("issues")
        self.assertEqual(r.state, ISSUES)
        self.assertEqual(r.items[0]["severity"], "Warning")

    def test_hang_is_stalled_and_killed(self):
        r = self._run("hang", stall_timeout=1)
        self.assertEqual(r.state, STALLED)

    def test_keyboard_interrupt_kills_group_and_writes_crashed_result(self):
        seen = []
        with mock.patch.object(runner._Streams, "pump", side_effect=KeyboardInterrupt):
            r = self._run("hang", on_spawn=seen.append)
        self.assertEqual(r.state, CRASHED)
        self.assertIn("interrupted by user", r.error or "")
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "result.json")))
        self.assertTrue(seen)
        self.assertFalse(runner._group_alive(seen[0]))

    def test_crash_with_malformed_output(self):
        r = self._run("crash")
        self.assertEqual(r.state, CRASHED)
        self.assertIn("reviewer exited with status", r.error or "")
        self.assertIn("without a valid structured verdict", r.error or "")
        import json
        with open(os.path.join(self.run_dir, "events.jsonl")) as fh:
            for line in fh:
                json.loads(line)  # must not raise

    def test_whitespace_stderr_does_not_hide_crash_diagnostic(self):
        r = self._run("crash_whitespace")
        self.assertEqual(r.state, CRASHED)
        self.assertIn("reviewer exited with status", r.error or "")

    def test_posthang_returns_clean_without_waiting(self):
        # M3: verdict present, process won't exit -> must finish CLEAN promptly.
        r = self._run("posthang", global_deadline=30)
        self.assertEqual(r.state, CLEAN)

    def test_provider_error(self):
        from claude_review_loop.states import PROVIDER_ERROR
        r = self._run("provider_error")
        self.assertEqual(r.state, PROVIDER_ERROR)
        self.assertIn("529", r.error or "")

    def test_forbidden_tool_is_invalid_and_recorded(self):
        r = self._run("forbidden_tool")
        self.assertEqual(r.state, INVALID)
        self.assertIn("Bash", r.error or "")
        self.assertEqual(r.forbidden_tool_uses[0]["tool"], "Bash")

    def test_out_of_scope_allowed_tool_is_invalid_and_recorded(self):
        r = self._run("out_of_scope_read", cwd=self.run_dir)
        self.assertEqual(r.state, INVALID)
        self.assertIn("out-of-scope Claude Read target", r.error or "")
        self.assertEqual(r.forbidden_tool_uses[0]["tool"], "Read")

    def test_forbidden_tool_error_precedes_provider_error(self):
        r = self._run("forbidden_provider_error")
        self.assertEqual(r.state, INVALID)
        self.assertIn("forbidden Claude tool use: Bash", r.error or "")
        self.assertIn("529 overloaded", r.error or "")
        self.assertLess(r.error.index("Bash"), r.error.index("529"))

    def test_missing_structured_output_error_reaches_result(self):
        r = self._run("missing_structured")
        self.assertEqual(r.state, INVALID)
        self.assertEqual(r.error, "missing structured output")

    def test_default_stdin_is_closed(self):
        r = self._run("stdin_empty")
        self.assertEqual(r.state, CLEAN)

    def test_input_path_supplies_stdin(self):
        prompt_path = os.path.join(self.run_dir, "prompt.txt")
        with open(prompt_path, "w") as fh:
            fh.write("review prompt")
        r = self._run("stdin_prompt", input_path=prompt_path)
        self.assertEqual(r.state, CLEAN)

    def test_on_spawn_receives_pgid(self):
        seen = []
        r = self._run("clean", on_spawn=lambda p: seen.append(p))
        self.assertEqual(r.state, CLEAN)
        self.assertTrue(seen and isinstance(seen[0], int))

    def test_on_spawn_failure_reaps_process_and_closes_pipes(self):
        spawned = []
        real_popen = runner.subprocess.Popen

        def capture_popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            spawned.append(proc)
            return proc

        def fail_spawn(_pgid):
            raise RuntimeError("ownership lost")

        with mock.patch.object(
            runner.subprocess, "Popen", side_effect=capture_popen
        ):
            result = self._run("hang", on_spawn=fail_spawn)
        self.assertEqual(result.state, CRASHED)
        self.assertIn("ownership lost", result.error or "")
        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].stdout)
        self.assertIsNotNone(spawned[0].stderr)
        self.assertTrue(spawned[0].stdout.closed)
        self.assertTrue(spawned[0].stderr.closed)
        self.assertFalse(runner._group_alive(spawned[0].pid))

    def test_kill_group_escalates_when_wrapper_exits_but_group_survives(self):
        proc = mock.Mock()
        proc.wait.side_effect = [None, None]
        with mock.patch("claude_review_loop.runner.os.killpg") as killpg, mock.patch(
            "claude_review_loop.runner._group_alive",
            side_effect=[True, False],
        ):
            runner._kill_group(proc, 12345, grace=0.01)

        self.assertEqual(
            killpg.call_args_list,
            [mock.call(12345, signal.SIGTERM), mock.call(12345, signal.SIGKILL)],
        )


if __name__ == "__main__":
    unittest.main()
