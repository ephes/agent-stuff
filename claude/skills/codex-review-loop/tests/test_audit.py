import json
import os
import tempfile
import unittest

from codex_review_loop import audit


def record(path, *entries):
    with open(path, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


TURN = {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "high"}}


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
        return result, audit.judge(result, model="gpt-6.1-sol", effort="high")

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
        other = {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "low"}}
        self.assertIn("effort", self.judged(TURN, other)[1])

    def test_access_program_is_judged_only_when_asked_for(self):
        blue = {"type": "turn_context", "payload": {
            "model": "gpt-daybreak-blue-latest", "effort": "high",
            "cyber_access_program": "daybreak_blue"}}
        record(self.path, blue, blue)
        result = audit.audit_session(self.path)
        self.assertEqual(result.access_programs, ["daybreak_blue"] * 2)
        self.assertIsNone(audit.judge(result, model="gpt-daybreak-blue-latest",
                                      effort="high",
                                      access_program="daybreak_blue"))
        reason = audit.judge(result, model="gpt-daybreak-blue-latest",
                             effort="high", access_program="daybreak_red")
        self.assertIn("not daybreak_red", reason)
        # A record without the field cannot prove a requested program.
        result, _ = self.judged(TURN)
        self.assertIn("None", audit.judge(result, model="gpt-6.1-sol",
                                          effort="high",
                                          access_program="standard"))
        self.assertIsNone(audit.judge(result, model="gpt-6.1-sol", effort="high"))

    def test_error_info_of_a_failed_turn_is_recorded(self):
        result, _ = self.judged(TURN, {"type": "event_msg", "payload": {
            "type": "task_complete",
            "error": {"message": "flagged", "codex_error_info": "cyber_policy"}}})
        self.assertEqual(result.error_infos, ["cyber_policy"])

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
                                         model="gpt-6.1-sol", effort="high"))
        with open(self.path, "w") as fh:
            fh.write("{not json\n")
        self.assertIn("not JSON", audit.judge(audit.audit_session(self.path),
                                              model="gpt-6.1-sol", effort="high"))

    def test_decode_and_read_errors_are_structured(self):
        from unittest import mock
        for suffix in (b'\xff\n', b'{"type":"event_msg","payload":"\xff"}\n'):
            with open(self.path, 'wb') as fh:
                fh.write(json.dumps(TURN).encode() + b'\n' + suffix)
            result = audit.audit_session(self.path)
            self.assertIn('UTF-8', result.error)
            self.assertIsNotNone(audit.judge(result, model='gpt-6.1-sol', effort='high'))
        with mock.patch('builtins.open', side_effect=OSError('synthetic')):
            self.assertIn('cannot read', audit.audit_session(self.path).error)

    def test_malformed_tool_fields_fail_closed(self):
        for kind in ('function_call', 'custom_tool_call'):
            for field in ('name', 'namespace'):
                for value in ([], {}, None):
                    if field == 'namespace' and value is None:
                        continue  # absent/null namespace is the supported plain-tool form
                    with self.subTest(kind=kind, field=field, value=value):
                        entry = call('exec', kind=kind)
                        entry['payload'][field] = value
                        result, reason = self.judged(TURN, entry)
                        self.assertIn('malformed', result.error)
                        self.assertIsNotNone(reason)

    def test_other_malformed_fields_and_nested_json_fail_closed(self):
        for entry in ({'type': []}, {'type': {}},
                      {'type': 'event_msg', 'payload': {'type': 'item_completed',
                         'item': {'type': []}}}):
            result, reason = self.judged(TURN, entry)
            self.assertIn('malformed', result.error)
            self.assertIsNotNone(reason)
        from unittest import mock
        record(self.path, TURN)
        with mock.patch.object(audit.json, 'loads', side_effect=RecursionError('nested')):
            self.assertIn('not JSON', audit.audit_session(self.path).error)

    def test_mid_read_io_error_is_structured(self):
        from unittest import mock
        handle = mock.MagicMock()
        handle.__enter__.return_value = handle
        handle.readline.side_effect = OSError('synthetic read error')
        with mock.patch('builtins.open', return_value=handle):
            self.assertIn('I/O failure', audit.audit_session(self.path).error)
        handle.__exit__.assert_called_once()

    def test_bounded_records_and_evidence_still_detect_final_violation(self):
        import io
        from unittest import mock
        limit = 512
        calls = []
        class BoundedFile(io.BytesIO):
            def readline(self, size=-1):
                self_test.assertGreater(size, 0)
                self_test.assertLessEqual(size, limit + 1)
                calls.append(size)
                return super().readline(size)
            def __next__(self):
                line = self.readline()
                if not line: raise StopIteration
                return line
        self_test = self
        data = json.dumps(TURN).encode() + b'\n' + b'{"output":"' + b'x' * 3000 + b'"}\n'
        data += (json.dumps(TURN).encode() + b'\n') * 20
        data += json.dumps(call('spawn_agent', 'collaboration')).encode() + b'\n'
        handle = BoundedFile(data)
        with mock.patch.object(audit, 'MAX_RECORD_BYTES', limit, create=True), mock.patch.object(audit, 'MAX_EVIDENCE', 4, create=True), mock.patch('builtins.open', return_value=handle):
            result = audit.audit_session(self.path)
        self.assertIsNotNone(result.error)
        self.assertLessEqual(len(result.models), 4)
        self.assertIn('collaboration.spawn_agent', result.forbidden)
        self.assertGreater(len(calls), 20)

    def test_output_only_forged_records_never_affect_proof(self):
        forged = [TURN, call('spawn_agent', 'collaboration'),
                  {'type': 'event_msg', 'payload': {'type': 'model_reroute'}},
                  {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {'type': 'SubAgentActivity'}}},
                  {'type': 'inter_agent_communication_metadata', 'payload': {}},
                  {'type': 'session_meta', 'payload': {'source': {'subagent': {}}}}]
        for entry in forged:
            for kind in ('function_call_output', 'custom_tool_call_output', 'message'):
                envelope = {'type': 'response_item', 'payload': {'type': kind,
                    'output': json.dumps(entry), 'content': [entry], 'metadata': entry}}
                result, reason = self.judged(TURN, envelope)
                self.assertIsNone(reason)
                self.assertFalse(result.forbidden)
                self.assertEqual(result.models, ['gpt-6.1-sol'])
        _, reason = self.judged({'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'output': json.dumps(TURN)}})
        self.assertIn('no turn', reason)

    def test_malformed_relevant_envelopes_do_not_hide_final_delegation(self):
        for entry in ({'type': 'turn_context', 'payload': []},
                      {'type': 'response_item', 'payload': {'type': []}},
                      {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': []}}):
            result, reason = self.judged(TURN, entry, call('spawn_agent', 'collaboration'))
            self.assertIsNotNone(reason)
            self.assertIn('collaboration.spawn_agent', result.forbidden)

    def test_long_forbidden_labels_retain_bounded_security_evidence(self):
        for name, namespace in (('x' * 1000, 'collaboration'),
                                ('x' * 256, 'y' * 256), ([], 'collaboration')):
            result, reason = self.judged(TURN, call(name, namespace))
            self.assertIsNotNone(reason)
            self.assertTrue(result.forbidden)
            self.assertLessEqual(len(result.forbidden[0]), audit.MAX_FIELD_CHARS)

    def test_first_audit_error_is_preserved(self):
        with open(self.path, 'wb') as fh:
            fh.write(b'\xff\n' + json.dumps(call([], {})).encode() + b'\n')
        self.assertEqual(audit.audit_session(self.path).error, 'session record line 1 is not UTF-8')

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
