import unittest
from pi_review_loop.monitor import Monitor, Decision
from pi_review_loop.states import (
    CLEAN, ISSUES, INVALID, CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR,
)


def mon():
    return Monitor(started_at=0.0, stall_timeout=180, retry_grace=30,
                   global_deadline=1500)


def agent_end_clean():
    return {"type": "agent_end", "messages": [
        {"role": "assistant", "content": [{"type": "text", "text": "REVIEW: CLEAN"}]},
    ]}


class TestMonitor(unittest.TestCase):
    def test_continue_when_fresh(self):
        m = mon()
        self.assertEqual(m.decide(now=10, proc_alive=True), Decision("continue", None))

    def test_agent_end_clean_finishes(self):
        m = mon()
        m.on_event(agent_end_clean(), now=5)
        d = m.decide(now=6, proc_alive=True)
        self.assertEqual(d, Decision("finish", CLEAN))
        self.assertEqual(m.verdict_state, CLEAN)

    def test_agent_end_without_verdict_is_invalid(self):
        m = mon()
        m.on_event({"type": "agent_end", "messages": [
            {"role": "assistant", "content": [{"type": "text", "text": "all good"}]},
        ]}, now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("finish", INVALID))

    def test_provider_giveup_before_crash(self):
        m = mon()
        m.on_event({"type": "auto_retry_end", "success": False, "finalError": "529"}, now=5)
        # Even though the process has also exited, provider error wins (keeps finalError).
        self.assertEqual(m.decide(now=6, proc_alive=False), Decision("kill", PROVIDER_ERROR))
        self.assertEqual(m.provider_error, "529")

    def test_process_exit_without_verdict_is_crashed(self):
        m = mon()
        self.assertEqual(m.decide(now=6, proc_alive=False), Decision("finish", CRASHED))

    def test_global_deadline(self):
        m = mon()
        m.on_event({"type": "message_update"}, now=1490)  # keep heartbeat fresh
        self.assertEqual(m.decide(now=1501, proc_alive=True), Decision("kill", STALLED))

    def test_stall_timeout(self):
        m = mon()
        m.on_event({"type": "message_update"}, now=10)
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

    def test_agent_end_issues_finishes_and_exposes_items(self):
        # The runner reads verdict_items to build ReviewResult — pin that contract.
        m = mon()
        m.on_event({"type": "agent_end", "messages": [
            {"role": "assistant", "content": [{"type": "text",
             "text": "REVIEW: ISSUES\n1. [Warning] x.py: tidy"}]},
        ]}, now=5)
        d = m.decide(now=6, proc_alive=True)
        self.assertEqual(d, Decision("finish", ISSUES))
        self.assertEqual(len(m.verdict_items), 1)
        self.assertEqual(m.verdict_items[0]["severity"], "Warning")

    def test_agent_end_during_retry_window_finishes(self):
        # Retry succeeded then agent emitted a verdict: verdict wins over the
        # still-open retry window (guards the branch ordering).
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 60000}, now=10)
        m.on_event(agent_end_clean(), now=15)
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
