import json
from pathlib import Path
import tempfile
import unittest
from codex_review_loop.result import ReviewResult


class TestResultContract(unittest.TestCase):
    def make(self, **kw):
        return ReviewResult(state='INVALID', items=[], model='synthetic-model',
                            cost=None, started_at=1, ended_at=2.125, **kw)

    def test_complete_provenance_round_trip_and_independent_defaults(self):
        values = dict(effort='high', access_program='synthetic-program',
            failure_kind='model_unproven', thread_id='invented-thread',
            session_record='/synthetic/rollout.jsonl', observed_models=['synthetic-model'],
            observed_efforts=['high'], observed_access_programs=['synthetic-program'],
            tool_uses=['exec'], forbidden_tool_uses=['synthetic.tool'],
            evidence_files=[{'file': 'evidence/01-test', 'redacted': True}],
            review_copy={'head': 'invented-head', 'removed': True},
            skipped_files=[{'path': 'synthetic'}], truncations=[{'section': 'test'}],
            redactions=[{'path': '[1]'}], baseline_ref='invented-base',
            baseline_commit='invented-snapshot', slice_id='invented-slice', round=2,
            convergence={'status': 'progress'}, structured_output={'verdict': 'ISSUES'},
            error='synthetic failure', raw_verdict_line='synthetic verdict')
        receipt = self.make(**values)
        payload = receipt.to_dict()
        self.assertEqual(set(payload), {'state','items','model','cost','started_at','ended_at',
                                      'duration_s','scoped_clean', *values})
        self.assertEqual(payload['duration_s'], 1.125)
        for field, value in values.items(): self.assertEqual(payload[field], value)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            receipt.write(path)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), payload)
        payload['evidence_files'][0]['file'] = 'changed'
        self.assertEqual(receipt.evidence_files[0]['file'], 'evidence/01-test')
        first, second = self.make(), self.make()
        for field in ('items','skipped_files','truncations','redactions','evidence_files',
                      'observed_models','observed_efforts','observed_access_programs',
                      'tool_uses','forbidden_tool_uses'):
            getattr(first, field).append('one')
            self.assertEqual(getattr(second, field), [])
        for field in ('effort','access_program','thread_id','session_record','failure_kind',
                      'review_copy','baseline_ref','baseline_commit','convergence',
                      'structured_output','error','raw_verdict_line','slice_id','round'):
            self.assertIsNone(second.to_dict()[field])
        second.state = 'CLEAN'
        second.redactions.append({'path': 'synthetic'})
        self.assertTrue(second.to_dict()['scoped_clean'])
