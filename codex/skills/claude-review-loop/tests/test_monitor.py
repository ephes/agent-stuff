import unittest
from claude_review_loop.monitor import Monitor, Decision
from claude_review_loop.states import (
    CLEAN, ISSUES, INVALID, CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR,
)


def mon():
    return Monitor(started_at=0.0, stall_timeout=180, retry_grace=30,
                   global_deadline=1500, review_root="/review-root")


def result_clean():
    return {"type": "result", "subtype": "success", "is_error": False,
            "result": "", "structured_output": {"verdict": "CLEAN", "findings": []},
            "total_cost_usd": 0.03}


class TestMonitor(unittest.TestCase):
    def test_continue_when_fresh(self):
        m = mon()
        self.assertEqual(m.decide(now=10, proc_alive=True), Decision("continue", None))

    def test_result_clean_finishes(self):
        m = mon()
        m.on_event(result_clean(), now=5)
        d = m.decide(now=6, proc_alive=True)
        self.assertEqual(d, Decision("finish", CLEAN))
        self.assertEqual(m.verdict_state, CLEAN)
        self.assertEqual(m.cost, 0.03)

    def test_assistant_event_does_not_finish_without_result(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "REVIEW: CLEAN"}],
        }}, now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("continue", None))
        self.assertEqual(m.assistant_text, "REVIEW: CLEAN")

    def test_result_without_structured_output_is_invalid(self):
        m = mon()
        m.on_event({"type": "result", "subtype": "success", "is_error": False,
                    "result": "REVIEW: CLEAN"}, now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("kill", INVALID))
        self.assertEqual(m.invalid_error, "missing structured output")

    def test_inconsistent_structured_output_has_invalid_error(self):
        m = mon()
        m.on_event({"type": "result", "subtype": "success", "is_error": False,
                    "structured_output": {"verdict": "CLEAN", "findings": [
                        {"severity": "Warning", "path": "x.py", "message": "issue"}
                    ]}}, now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("kill", INVALID))
        self.assertEqual(m.invalid_error, "CLEAN structured verdict must have no findings")

    def test_provider_giveup_before_crash(self):
        m = mon()
        m.on_event({"type": "result", "subtype": "error", "is_error": True,
                    "api_error_status": "529"}, now=5)
        # Even though the process has also exited, provider error wins (keeps finalError).
        self.assertEqual(m.decide(now=6, proc_alive=False), Decision("kill", PROVIDER_ERROR))
        self.assertEqual(m.provider_error, "529")

    def test_process_exit_without_verdict_is_crashed(self):
        m = mon()
        self.assertEqual(m.decide(now=6, proc_alive=False), Decision("finish", CRASHED))

    def test_global_deadline(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {}}, now=1490)  # keep heartbeat fresh
        self.assertEqual(m.decide(now=1501, proc_alive=True), Decision("kill", STALLED))

    def test_stall_timeout(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {}}, now=10)
        self.assertEqual(m.decide(now=10 + 181, proc_alive=True), Decision("kill", STALLED))

    def test_retry_window_suspends_stall(self):
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=10)
        # retry_deadline = 10 + 2 + 30 = 42; at now=41 still inside -> continue.
        self.assertEqual(m.decide(now=41, proc_alive=True), Decision("continue", None))

    def test_retry_window_expired(self):
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=10)
        # past retry_deadline (42) with no auto_retry_end -> STALLED_RETRY
        self.assertEqual(m.decide(now=43, proc_alive=True), Decision("kill", STALLED_RETRY))

    def test_retry_end_success_clears_window(self):
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=10)
        m.on_event({"type": "auto_retry_end", "success": True}, now=12)
        # window cleared; fresh heartbeat at 12; at 50 well within stall timeout
        self.assertEqual(m.decide(now=50, proc_alive=True), Decision("continue", None))

    def test_result_issues_finishes_and_exposes_items(self):
        # The runner reads verdict_items to build ReviewResult - pin that contract.
        m = mon()
        m.on_event({"type": "result", "subtype": "success", "is_error": False,
                    "structured_output": {"verdict": "ISSUES", "findings": [
                        {"severity": "Warning", "path": "x.py", "message": "tidy"}
                    ]}}, now=5)
        d = m.decide(now=6, proc_alive=True)
        self.assertEqual(d, Decision("finish", ISSUES))
        self.assertEqual(len(m.verdict_items), 1)
        self.assertEqual(m.verdict_items[0]["severity"], "Warning")

    def test_forbidden_tool_use_invalidates_even_a_clean_result(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}}
        ]}}, now=4)
        m.on_event(result_clean(), now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("kill", INVALID))
        self.assertEqual(m.forbidden_tool_uses[0]["tool"], "Bash")

    def test_unnamed_tool_use_is_forbidden(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "input": {"path": "x"}}
        ]}}, now=4)
        self.assertEqual(m.decide(now=5, proc_alive=True), Decision("kill", INVALID))
        self.assertEqual(m.forbidden_tool_uses[0]["tool"], "<unnamed>")

    def test_allowed_read_tool_does_not_invalidate(self):
        m = mon()
        m.on_event({"type": "stream_event", "event": {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Read", "input": {"file_path": "x"}},
        }}, now=4)
        m.on_event(result_clean(), now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("finish", CLEAN))

    def test_out_of_scope_read_invalidates_clean_result(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/etc/hosts"}}
        ]}}, now=4)
        m.on_event(result_clean(), now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("kill", INVALID))
        self.assertIn("out-of-scope Claude Read target", m.invalid_error)
        self.assertEqual(m.forbidden_tool_uses[0]["tool"], "Read")

    def test_traversal_grep_target_is_invalid(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Grep", "input": {
                "pattern": "root", "path": "../outside"
            }}
        ]}}, now=4)
        self.assertEqual(m.decide(now=5, proc_alive=True), Decision("kill", INVALID))
        self.assertIn("out-of-scope Claude Grep target", m.invalid_error)

    def test_tilde_read_target_is_invalid(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "~/.ssh/config"}}
        ]}}, now=4)
        self.assertEqual(m.decide(now=5, proc_alive=True), Decision("kill", INVALID))
        self.assertIn("out-of-scope Claude Read target", m.invalid_error)

    def test_absolute_glob_pattern_is_invalid(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Glob", "input": {"pattern": "/etc/*"}}
        ]}}, now=4)
        self.assertEqual(m.decide(now=5, proc_alive=True), Decision("kill", INVALID))
        self.assertIn("out-of-scope Claude Glob pattern", m.invalid_error)

    def test_directory_scoped_grep_defaults_to_review_root(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "needle"}}
        ]}}, now=4)
        m.on_event(result_clean(), now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("finish", CLEAN))

    def test_empty_stream_start_defers_inspection_target_validation(self):
        m = mon()
        m.on_event({"type": "stream_event", "event": {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Read", "input": {}},
        }}, now=4)
        self.assertEqual(m.decide(now=5, proc_alive=True), Decision("continue", None))

    def test_structured_output_transport_is_not_forbidden(self):
        m = mon()
        m.on_event({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "StructuredOutput", "input": {
                "verdict": "CLEAN", "findings": []
            }}
        ]}}, now=4)
        m.on_event(result_clean(), now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("finish", CLEAN))
        self.assertFalse(m.forbidden_tool_uses)

    def test_terminal_result_during_retry_window_finishes(self):
        # Retry remained open when a terminal result arrived: verdict wins over the
        # still-open retry window (guards the branch ordering).
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 60000}, now=10)
        m.on_event(result_clean(), now=15)
        self.assertEqual(m.decide(now=16, proc_alive=True), Decision("finish", CLEAN))

    def test_second_retry_window_is_rearmed(self):
        # After a successful retry clears the window, a second retry must re-arm it
        # (else a second stall would be mis-killed as STALLED, not STALLED_RETRY).
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=10)
        m.on_event({"type": "auto_retry_end", "success": True}, now=12)
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=20)
        # second window: retry_deadline = 20 + 2 + 30 = 52; at 53 expired
        self.assertEqual(m.decide(now=53, proc_alive=True), Decision("kill", STALLED_RETRY))

    def test_auto_retry_start_without_delayms_uses_grace_only(self):
        m = mon()
        m.on_event({"type": "auto_retry_start"}, now=10)  # no delayMs key
        # window = now + 0 + retry_grace(30) = 40; at 39 inside, at 41 expired
        self.assertEqual(m.decide(now=39, proc_alive=True), Decision("continue", None))
        self.assertEqual(m.decide(now=41, proc_alive=True), Decision("kill", STALLED_RETRY))


if __name__ == "__main__":
    unittest.main()
