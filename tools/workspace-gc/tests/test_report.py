import json
import unittest
from unittest import mock
from workspace_gc import report, inventory, empties, husks
from tests.helpers import ok_signals


class TestReport(unittest.TestCase):
    def setUp(self):
        patcher=mock.patch.object(report.socket,'gethostname',return_value='synthetic-host')
        patcher.start(); self.addCleanup(patcher.stop)

    def fixture(self):
        co=inventory.Checkout(path='/synthetic/λ',root='/synthetic',workspace='/synthetic',kind='clone',cls='A',size_kb=10)
        return inventory.Inventory(roots=['/synthetic'],checkouts=[co],signals=ok_signals())

    def test_terminal_controls_are_escaped_but_json_identity_is_raw(self):
        value='λ\x1b]8;;https://synthetic.example\x07link\x1b]8;;\x07\r\nforged\trow'
        inv=self.fixture(); co=inv.checkouts[0]
        co.path='/synthetic/'+value; co.branch=value; co.last_commit=value
        co.reasons=[value]; co.notes=[value]; co.payloads=[{'path':value,'kb':1}]
        co.unpushed_commits=[value]; co.unpushed_hints=[value]; co.cls='C'
        inv.husks=[husks.Husk(path='/synthetic/husk-'+value,entries=[{'path':value,'kb':1,'payload':False}],git_dirs=[value],kept=value,note=value,outcome=value)]
        inv.empty_dirs=[empties.EmptyDir(path='/synthetic/empty-'+value,reason=value)]
        inv.prune={value:[value]}
        with mock.patch.object(report.os,'scandir',side_effect=OSError('synthetic root')):
            text=report.to_text(inv,'synthetic-time')
            data=report.to_json(inv,'synthetic-time')
        self.assertNotIn('\x1b',text); self.assertNotIn('\r',text); self.assertNotIn('\t',text)
        self.assertNotIn('\nforged',text)
        self.assertIn('λ',text); self.assertIn('\\nforged',text)
        self.assertEqual(data['checkouts'][0]['path'],co.path)
        self.assertEqual(data['husks'][0]['entries'][0]['path'],value)
        self.assertEqual(json.loads(json.dumps(data))['checkouts'][0]['reasons'],[value])

    def test_dry_refused_and_partial_receipts_agree(self):
        for mode in ('dry','refused','partial'):
            inv=self.fixture()
            gone=inventory.Checkout(path='/synthetic/gone',root='/synthetic',workspace='/synthetic',kind='worktree',cls='A',size_kb=20)
            inv.empty_dirs=[empties.EmptyDir(path='/synthetic/empty',removable=True)]
            inv.husks=[husks.Husk(path='/synthetic/stale',kb=30,stale=True),husks.Husk(path='/synthetic/cache',kb=10,payload_kb=7,removable=True)]
            if mode=='refused': inv.run=inventory.Run(refused=['synthetic incomplete source'])
            if mode=='partial':
                inv.run=inventory.Run(removed=[gone],skipped=1,outcomes=[{'path':'/synthetic/failure','outcome':'skipped: synthetic'}])
                inv.empty_dirs[0].removed=True
                inv.husks[0].removed=True; inv.husks[0].removed_what='directory'; inv.husks[0].removed_kb=30
                inv.husks[1].removed=True; inv.husks[1].removed_what='caches'; inv.husks[1].removed_kb=7
            with mock.patch.object(report.os,'scandir',side_effect=OSError('inaccessible')):
                data=report.to_json(inv,'synthetic-time'); text=report.to_text(inv,'synthetic-time')
            self.assertEqual(data['totals']['A']['count'],1)
            self.assertEqual(data['totals']['A']['kb'],10)
            self.assertEqual(data['removed_kb'],20 if mode=='partial' else 0)
            self.assertEqual(data['mode'],{'dry':'dry-run','refused':'refused','partial':'applied'}[mode])
            self.assertIn(data['summary'],text)
            self.assertIn('roots unreadable',data['summary'])
            if mode=='partial':
                self.assertEqual(len(data['husks_removed']),2)
                self.assertEqual(len(data['skipped']),1)
                self.assertIn('0 stale and removable',text)
                self.assertIn('0 cache-only and removable',text)
                self.assertIn('1 skipped',data['summary'])
            if mode=='refused': self.assertEqual(data['removed'],[])

    def test_scan_human_projection_and_json_outcome_identity(self):
        import io
        from workspace_gc import cli, remove
        for structured in (False,True):
            inv=self.fixture()
            inv.checkouts[0].path='/synthetic/unsafe\x1b\r\nforged'
            outcome='removed clone '+inv.checkouts[0].path
            args=cli.parser().parse_args(['scan','--apply','--root','/synthetic']+(['--json'] if structured else []))
            args.regenerable_file=None
            with mock.patch.object(cli,'_build',return_value=inv), mock.patch.object(inventory,'prune_targets',return_value=[]), mock.patch.object(remove,'remove_checkout',return_value=outcome), mock.patch.object(empties,'remove'), mock.patch.object(husks,'remove'):
                out=io.StringIO(); self.assertEqual(cli.cmd_scan(args,inv.signals,out),0)
            if structured:
                self.assertEqual(json.loads(out.getvalue())['removed'][0]['outcome'],outcome)
            else:
                self.assertNotIn('\x1b',out.getvalue()); self.assertNotIn('\r',out.getvalue())
                self.assertNotIn('\nforged',out.getvalue())

    def test_no_size_scan_retains_counts_with_zero_size_values(self):
        inv=self.fixture(); inv.checkouts[0].size_kb=0
        with mock.patch.object(report.os,'scandir',return_value=iter([])):
            data=report.to_json(inv,'synthetic-time')
        self.assertEqual(data['totals']['A']['count'],1)
        self.assertEqual(data['totals']['A']['kb'],0)
        self.assertEqual(data['removed_kb'],0)
        self.assertIn('1 removable (0K)',data['summary'])

    def test_remove_and_report_stdout_escape_untrusted_fields(self):
        import io, tempfile
        from workspace_gc import cli
        value='unsafe\x1b\r\nforged\trow'
        inv=self.fixture(); co=inv.checkouts[0]
        co.cls='C'; co.path='/synthetic/'+value
        co.reasons=[value]; co.unpushed_commits=[value]; co.unpushed_hints=[value]
        args=cli.parser().parse_args(['remove','--root','/synthetic',co.path])
        args.regenerable_file=None
        with mock.patch.object(cli,'_build',return_value=inv):
            out=io.StringIO(); self.assertEqual(cli.cmd_remove(args,inv.signals,out),1)
        for control in ('\x1b','\r','\t','\nforged'): self.assertNotIn(control,out.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            args=cli.parser().parse_args(['report','--out-dir',tmp,'--work-item','synthetic'])
            with mock.patch.object(cli,'_build',return_value=inv), mock.patch.object(inventory,'prune_targets',return_value=[]), mock.patch.object(cli,'_upsert_item',return_value=value):
                out=io.StringIO(); self.assertEqual(cli.cmd_report(args,inv.signals,out),0)
            for control in ('\x1b','\r','\t','\nforged'): self.assertNotIn(control,out.getvalue())
