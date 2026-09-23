import json
import os
import tempfile
import unittest

from codex_review_loop import audit


def record(path, *entries):
    with open(path, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


TURN = {"type": "turn_context", "payload": {"model": "gpt-6-sol", "effort": "high"}}


def call(name, namespace=None, kind="function_call"):
    payload = {"type": kind, "name": name}
    if namespace:
        payload["namespace"] = namespace
    return {"type": "response_item", "payload": payload}


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "r.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def judged(self, *entries):
        record(self.path, *entries)
        result = audit.audit_session(self.path)
        return result, audit.judge(result, model="gpt-6-sol", effort="high")

    def test_a_pinned_run_passes(self):
        result, reason = self.judged(TURN, call("exec", kind="custom_tool_call"),
                                     call("wait"), TURN)
        self.assertIsNone(reason)
        self.assertEqual(result.forbidden, [])
        self.assertEqual(result.tool_uses, ["exec", "wait"])

    def test_any_turn_on_another_model_fails(self):
        other = {"type": "turn_context", "payload": {"model": "gpt-5.6-sol", "effort": "high"}}
        self.assertIn("gpt-5.6-sol", self.judged(TURN, other)[1])

    def test_any_turn_at_another_effort_fails(self):
        other = {"type": "turn_context", "payload": {"model": "gpt-6-sol", "effort": "low"}}
        self.assertIn("effort", self.judged(TURN, other)[1])

    def test_no_turn_fails(self):
        self.assertIn("no turn", self.judged({"type": "session_meta", "payload": {}})[1])

    def test_a_reroute_record_fails(self):
        _, reason = self.judged(TURN, {"type": "event_msg",
                                       "payload": {"type": "model_reroute"}})
        self.assertIn("reroute", reason)

    def test_the_word_reroute_inside_content_is_not_a_reroute(self):
        _, reason = self.judged(TURN, {"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec",
            "input": "grep -n model_reroute audit.py"}})
        self.assertIsNone(reason)

    def test_delegation_and_unlisted_tools_are_forbidden(self):
        for entry, label in (
                (call("spawn_agent", "collaboration"), "collaboration.spawn_agent"),
                (call("wait_agent", "collaboration"), "collaboration.wait_agent"),
                (call("web_search"), "web_search"),
                (call("exec", "mcp__x"), "mcp__x.exec"),
                ({"type": "event_msg", "payload": {"type": "item_completed",
                  "item": {"type": "SubAgentActivity"}}}, "SubAgentActivity"),
                ({"type": "inter_agent_communication_metadata", "payload": {}},
                 "inter_agent_communication_metadata"),
                ({"type": "session_meta", "payload": {"source": {"subagent": {}}}},
                 "session is a subagent thread")):
            with self.subTest(label=label):
                result, _ = self.judged(TURN, entry)
                self.assertEqual(result.forbidden, [label])

    def test_missing_or_broken_record_is_an_error(self):
        self.assertIsNotNone(audit.judge(audit.audit_session(None),
                                         model="gpt-6-sol", effort="high"))
        with open(self.path, "w") as fh:
            fh.write("{not json\n")
        self.assertIn("not JSON", audit.judge(audit.audit_session(self.path),
                                              model="gpt-6-sol", effort="high"))

    def test_find_session_record_requires_exactly_one_match(self):
        day = os.path.join(self.tmp.name, "sessions", "2026", "09", "23")
        os.makedirs(day)
        self.assertIsNone(audit.find_session_record(self.tmp.name, "abc"))
        path = os.path.join(day, "rollout-2026-09-23T10-00-00-abc.jsonl")
        open(path, "w").close()
        self.assertEqual(audit.find_session_record(self.tmp.name, "abc"), path)
        self.assertIsNone(audit.find_session_record(self.tmp.name, None))
        self.assertIsNone(audit.find_session_record(self.tmp.name, "*"))


if __name__ == "__main__":
    unittest.main()
