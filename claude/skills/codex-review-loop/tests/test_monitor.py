import unittest

from codex_review_loop.monitor import Monitor


def monitor(**kw):
    args = dict(started_at=0.0, stall_timeout=10.0, global_deadline=100.0,
                exit_grace=5.0)
    args.update(kw)
    return Monitor(**args)


class TestMonitor(unittest.TestCase):
    def test_continues_while_active(self):
        m = monitor()
        m.on_event({"type": "thread.started", "thread_id": "t"}, 1.0)
        self.assertEqual(m.decide(5.0, True).action, "continue")
        self.assertEqual(m.thread_id, "t")

    def test_stall_and_deadline(self):
        m = monitor()
        d = m.decide(11.0, True)
        self.assertEqual((d.action, d.state, d.kind), ("kill", "STALLED", "stall"))
        m = monitor(stall_timeout=1000.0)
        m.note_activity(99.0)
        d = m.decide(101.0, True)
        self.assertEqual((d.action, d.state, d.kind), ("kill", "STALLED", "deadline"))

    def test_a_launch_that_starts_no_thread_is_a_startup_stall(self):
        # Output on stderr is activity, but no thread: a Codex held before its
        # first event ends at the startup timeout, not the stall timeout.
        m = monitor(stall_timeout=1000.0, startup_timeout=5.0,
                    binary="/opt/x/codex")
        m.note_activity(4.0)
        self.assertEqual(m.decide(5.0, True).action, "continue")
        d = m.decide(6.0, True)
        self.assertEqual((d.action, d.state, d.kind), ("kill", "STALLED", "stall"))
        self.assertIn("--startup-timeout (5s)", d.error)
        self.assertIn("never started a thread", d.error)
        self.assertIn("Gatekeeper", d.error)
        self.assertIn("`xattr -p com.apple.quarantine /opt/x/codex`", d.error)
        spaced = monitor(startup_timeout=1.0, binary="/Applications/My Codex/codex")
        self.assertIn("'/Applications/My Codex/codex'", spaced.decide(2.0, True).error)
        self.assertNotIn("\n", d.error)

    def test_a_started_thread_disarms_the_startup_timeout(self):
        m = monitor(stall_timeout=1000.0, startup_timeout=5.0)
        m.on_event({"type": "thread.started", "thread_id": "t"}, 1.0)
        m.note_activity(50.0)
        self.assertEqual(m.decide(60.0, True).action, "continue")

    def test_every_stall_says_why(self):
        d = monitor().decide(11.0, True)
        self.assertIn("--stall-timeout (10s)", d.error)
        self.assertIn("never started a thread", d.error)
        m = monitor()
        m.on_event({"type": "thread.started", "thread_id": "t"}, 1.0)
        d = m.decide(12.0, True)
        self.assertIn("--stall-timeout (10s)", d.error)
        self.assertNotIn("Gatekeeper", d.error)
        m = monitor(stall_timeout=1000.0)
        m.on_event({"type": "thread.started", "thread_id": "t"}, 1.0)
        m.note_activity(99.0)
        self.assertIn("--review-deadline", m.decide(101.0, True).error)

    def test_activity_resets_the_stall_timer(self):
        m = monitor()
        m.note_activity(9.0)
        self.assertEqual(m.decide(15.0, True).action, "continue")

    def test_turn_failed_is_a_provider_error(self):
        m = monitor()
        m.on_event({"type": "turn.failed", "error": {"message": "at capacity"}}, 1.0)
        d = m.decide(1.0, True)
        self.assertEqual((d.action, d.state), ("kill", "PROVIDER_ERROR"))
        self.assertEqual(m.turn_failure, "at capacity")

    def test_collab_item_is_forbidden(self):
        m = monitor()
        m.on_event({"type": "item.started",
                    "item": {"type": "collab_tool_call", "tool": "spawn_agent"}}, 1.0)
        d = m.decide(1.0, False)
        self.assertEqual((d.action, d.state, d.kind), ("finish", "INVALID", "forbidden_tool"))

    def test_completed_turn_waits_then_kills_without_a_state(self):
        m = monitor()
        m.on_event({"type": "turn.completed"}, 2.0)
        self.assertEqual(m.decide(6.0, True).action, "continue")
        d = m.decide(8.0, True)
        self.assertEqual((d.action, d.state), ("kill", None))
        # A completed turn is never a stall, however long the exit takes.
        self.assertEqual(monitor().decide(0.0, False).action, "finish")

    def test_exit_is_finish_to_classify(self):
        d = monitor().decide(1.0, False)
        self.assertEqual((d.action, d.state), ("finish", None))


if __name__ == "__main__":
    unittest.main()
