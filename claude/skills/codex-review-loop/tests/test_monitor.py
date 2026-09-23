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
