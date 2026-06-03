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


if __name__ == "__main__":
    unittest.main()
