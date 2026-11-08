import os
from unittest import mock
from tests.helpers import GitFixture, SourceStatus, WorkRef, ok_signals
from workspace_gc import cli, signals, remove


class TestLateClaims(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.clone_path = ''

    def test_checkout_refresh_after_remote_proof_for_both_entrypoints(self):
        for command in ('scan', 'remove'):
            for claim in ('process', 'pane', 'work', 'parent', 'unreadable', 'none'):
                with self.subTest(command=command, claim=claim):
                    self.clone_path = self.clone(self.url, 'ws-' + command + '-' + claim)
                    process = ([self.clone_path], SourceStatus('ok')) if claim == 'process' else ([], SourceStatus('ok'))
                    panes = ([self.clone_path], SourceStatus('ok')) if claim == 'pane' else ([], SourceStatus('ok'))
                    refs = [WorkRef('synthetic', 'active', os.path.dirname(self.clone_path) if claim == 'parent' else self.clone_path)] if claim in ('work', 'parent') else []
                    status = SourceStatus('error', 'synthetic refresh failure') if claim == 'unreadable' else SourceStatus('ok')
                    with mock.patch.object(signals, 'read_process_cwds', return_value=process), mock.patch.object(signals, 'read_herdr', return_value=panes), mock.patch.object(signals, 'read_work_items', return_value=(refs,status)):
                        args = [command, '--apply'] + ([self.clone_path] if command == 'remove' else [])
                        code, text = self.cli(*args, signals=ok_signals())
                    if claim == 'none':
                        self.assertEqual(code, 0, text)
                        self.assertFalse(os.path.exists(self.clone_path))
                    else:
                        self.assertNotEqual(code, 0, text)
                        self.assertTrue(os.path.isdir(self.clone_path))
                        self.assertIn('in use' if claim in ('process', 'pane') else
                                      'active work item' if claim in ('work', 'parent') else
                                      'incomplete now', text)

    def test_refreshed_signals_keep_original_active_claims(self):
        original = ok_signals(work_refs=[WorkRef('synthetic', 'active', self.ws)])
        with mock.patch.object(signals, 'read_process_cwds', return_value=([],SourceStatus('ok'))), mock.patch.object(signals, 'read_herdr', return_value=([],SourceStatus('ok'))), mock.patch.object(signals, 'read_work_items', return_value=([],SourceStatus('ok'))):
            live = signals.refresh(original)
        self.assertEqual(live.work_refs, original.work_refs)

class TestLateCleanupClaims(GitFixture):
    def test_empty_and_husk_refresh_new_panes_work_claims_and_failures(self):
        import time
        from workspace_gc import empties, husks
        for kind in ('empty', 'husk'):
            for claim in ('pane', 'work', 'parent', 'unreadable', 'none'):
                with self.subTest(kind=kind, claim=claim):
                    path = os.path.join(self.ws, 'ws-' + kind + '-' + claim)
                    os.mkdir(path)
                    if kind == 'husk':
                        with open(os.path.join(path, 'note.txt'), 'w') as fh:
                            fh.write('synthetic')
                    panes = [path] if claim == 'pane' else []
                    refs = [WorkRef('synthetic', 'active', self.ws if claim == 'parent' else path)] if claim in ('work','parent') else []
                    status = SourceStatus('error', 'synthetic') if claim == 'unreadable' else SourceStatus('ok')
                    with mock.patch.object(signals, 'read_process_cwds', return_value=([],SourceStatus('ok'))), mock.patch.object(signals, 'read_herdr', return_value=(panes,SourceStatus('ok'))), mock.patch.object(signals, 'read_work_items', return_value=(refs,status)), mock.patch.object(empties, '_now', return_value=time.time()+24*3600), mock.patch.object(husks, '_now', return_value=time.time()+24*3600):
                        if kind == 'empty':
                            entry = empties.EmptyDir(path=path, removable=True)
                            empties.remove([entry], [], ok_signals())
                        else:
                            entry = husks.Husk(path=path, stale=True)
                            husks.remove([entry], [self.ws], [], ok_signals(), 0, 1)
                    if claim == 'none':
                        self.assertTrue(entry.removed, entry.reason if kind == 'empty' else entry.outcome)
                        self.assertFalse(os.path.exists(path))
                    else:
                        self.assertFalse(entry.removed)
                        self.assertTrue(os.path.isdir(path))
                        reason = entry.reason if kind == 'empty' else entry.outcome
                        self.assertIn('in use' if claim == 'pane' else
                                      'active work item' if claim in ('work', 'parent') else
                                      'unreadable now', reason)
