import io
import json
import unittest
from unittest import mock
from workspace_gc import cli, inventory, empties, husks, remove
from workspace_gc.git import GitError
from tests.helpers import ok_signals


class TestPartialOutcomes(unittest.TestCase):
    def fixture(self):
        co = inventory.Checkout(path='/synthetic/ws/repo', root='/synthetic', workspace='/synthetic/ws', kind='clone', cls='A', size_kb=10)
        inv = inventory.Inventory(roots=['/synthetic'], checkouts=[co], signals=ok_signals())
        args = cli.parser().parse_args(['scan','--root','/synthetic','--main-root','/synthetic/main','--apply'])
        args.regenerable_file=None
        return args, inv

    def test_prune_failure_keeps_partial_receipt_and_continues_cleanup(self):
        args, inv = self.fixture()
        with mock.patch.object(cli, '_build', return_value=inv), mock.patch.object(inventory, 'prune_targets', return_value=['/synthetic/owner']), mock.patch.object(remove, 'remove_checkout', return_value='removed clone /synthetic/ws/repo'), mock.patch.object(remove, 'prune', side_effect=GitError('synthetic prune failure')), mock.patch.object(empties, 'remove') as empty_cleanup, mock.patch.object(husks, 'remove') as husk_cleanup:
            out = io.StringIO()
            code = cli.cmd_scan(args, inv.signals, out)
        self.assertEqual(code, 1)
        empty_cleanup.assert_called_once()
        husk_cleanup.assert_called_once()
        self.assertEqual(len(inv.run.removed), 1)
        data = cli.rep.to_json(inv, 'synthetic-time')
        self.assertEqual(data['removed_kb'], 10)
        self.assertIn('/synthetic/owner', data['prune_errors'])
        self.assertIn('synthetic prune failure', cli.rep.to_text(inv, 'synthetic-time'))
        self.assertIn('synthetic prune failure', out.getvalue())

    def test_attempted_cleanup_failures_count_but_expected_keeps_do_not(self):
        for fault in ('I/O failure', 'late safety claim'):
            args, inv = self.fixture()
            inv.empty_dirs = [empties.EmptyDir(path='/synthetic/empty', removable=True), empties.EmptyDir(path='/synthetic/kept', reason='protected')]
            inv.husks = [husks.Husk(path='/synthetic/husk', stale=True), husks.Husk(path='/synthetic/kept-husk', kept='protected')]
            def fail_empty(entries, *a, **kw):
                entries[0].reason = fault
                entries[0].removable = False
            def fail_husk(entries, *a, **kw):
                entries[0].outcome = fault
                entries[0].stale = False
            with mock.patch.object(inventory, 'prune_targets', return_value=[]), mock.patch.object(remove, 'remove_checkout', return_value='removed clone /synthetic/ws/repo'), mock.patch.object(empties, 'remove', side_effect=fail_empty), mock.patch.object(husks, 'remove', side_effect=fail_husk):
                run = cli._apply(args, inv)
            self.assertEqual(cli._exit_code(run), 1)
            self.assertEqual(run.skipped, 2)
            self.assertEqual(len(run.removed), 1)
            self.assertEqual(len(cli.rep.to_json(inv)['skipped']), 2)
            self.assertIn(fault, cli.rep.to_text(inv))

    def test_nonzero_prune_command_is_a_failure(self):
        from subprocess import CompletedProcess
        with mock.patch.object(remove.git, 'run') as run:
            def failed(*a, **kw):
                if kw.get('check', True): raise GitError('prune failed')
                return CompletedProcess([], 1, '', 'prune failed')
            run.side_effect = failed
            with self.assertRaises(GitError): remove.prune('/synthetic/owner')

    def test_report_publishes_both_receipts_after_partial_prune_failure(self):
        import tempfile
        from pathlib import Path
        args, inv = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            args = cli.parser().parse_args(['report','--out-dir',tmp,'--apply','--root','/synthetic'])
            args.regenerable_file=None
            with mock.patch.object(cli, '_build', return_value=inv), mock.patch.object(inventory, 'prune_targets', return_value=['/synthetic/owner']), mock.patch.object(remove, 'remove_checkout', return_value='removed clone /synthetic/ws/repo'), mock.patch.object(remove, 'prune', side_effect=GitError('synthetic prune failure')), mock.patch.object(empties, 'remove'), mock.patch.object(husks, 'remove'):
                self.assertEqual(cli.cmd_report(args,inv.signals,io.StringIO()),1)
            data=json.loads(Path(tmp,'latest.json').read_text())
            self.assertEqual(data['removed_kb'],10)
            self.assertIn('/synthetic/owner',data['prune_errors'])
            self.assertIn('synthetic prune failure',Path(tmp,'latest.txt').read_text())

    def test_removed_clone_is_not_pruned(self):
        args, inv = self.fixture()
        with mock.patch.object(inventory, 'prune_targets', return_value=[inv.checkouts[0].path,'/synthetic/owner']), mock.patch.object(remove,'remove_checkout',return_value='removed clone /synthetic/ws/repo'), mock.patch.object(remove,'prune',return_value=[]) as prune, mock.patch.object(empties,'remove'), mock.patch.object(husks,'remove'):
            run=cli._apply(args,inv)
        prune.assert_called_once_with('/synthetic/owner')
        self.assertEqual(run.skipped,0)

    def test_single_remove_reports_owner_prune_failure(self):
        args, inv=self.fixture()
        co=inv.checkouts[0]; co.kind='worktree'; co.owner_repo='/synthetic/owner'
        args.path=co.path
        with mock.patch.object(cli,'_build',return_value=inv), mock.patch.object(remove,'remove_checkout',return_value='removed worktree /synthetic/ws/repo'), mock.patch.object(remove,'prune',side_effect=GitError('synthetic owner prune')):
            out=io.StringIO()
            self.assertEqual(cli.cmd_remove(args,inv.signals,out),1)
        self.assertIn('removed worktree',out.getvalue())
        self.assertIn('prune failed',out.getvalue())

    def test_real_git_prune_failure_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GitError): remove.prune(tmp)
