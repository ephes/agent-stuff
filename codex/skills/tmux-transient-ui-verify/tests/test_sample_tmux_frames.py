import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]


def sampler(agent):
    path=ROOT/agent/'skills/tmux-transient-ui-verify/scripts/sample_tmux_frames.py'
    spec=importlib.util.spec_from_file_location('sampler_'+agent,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSamplerPreflight(unittest.TestCase):
    def test_invalid_identity_and_numeric_domains_have_no_side_effects(self):
        cases=[['--target','pane\n=x'],['--target','pane\r=x'],
               ['--target','a=one','--target','a=two'],
               ['--target','a=one','--send','a=one','--send','a=two'],
               ['--target','a=one','--send','b=unknown']]
        cases += [['--target','a=one','--interval',value] for value in ('nan','inf','-inf','-1')]
        for agent in ('codex','claude'):
            module=sampler(agent)
            for args in cases+([['--target','a=one','--max-row-delta','-1']] if agent=='codex' else []):
                with self.subTest(agent=agent,args=args), tempfile.TemporaryDirectory() as tmp:
                    out=Path(tmp)/'out'
                    with mock.patch.object(sys,'argv',['sampler','--out',str(out),'--frames','1',*args]), mock.patch.object(module,'run_tmux',return_value=b'Working...\n') as capture, mock.patch.object(module,'send_prompt') as send:
                        with self.assertRaises(SystemExit) as raised: module.main()
                    self.assertEqual(raised.exception.code,2)
                    capture.assert_not_called(); send.assert_not_called()
                    self.assertFalse(out.exists())

    def test_safe_labels_and_finite_zero_or_fractional_intervals(self):
        for agent in ('codex','claude'):
            module=sampler(agent)
            self.assertEqual(module.parse_label_value('pane-1.x=y',option='--target'),('pane-1.x','y'))
            for interval in ('0','0.25'):
                with tempfile.TemporaryDirectory() as tmp:
                    out=Path(tmp)/'out'
                    with mock.patch.object(sys,'argv',['sampler','--out',str(out),'--target','a=one','--frames','1','--interval',interval]), mock.patch.object(module,'run_tmux',return_value=b'Working...\n'):
                        self.assertEqual(module.main(),0)
                    self.assertTrue((out/'summary.json').exists())

    def test_missing_required_comparison_markers_fail(self):
        module=sampler('codex')
        for left,right in (('', ''),('', 'marker'),('marker','')):
            metrics=[]
            for label,text in (('a',left),('b',right)):
                rows,_=module.frame_metrics(label=label,frame_index=0,text=text,needles=['marker'],transient_needles=[])
                metrics.extend(rows)
            deltas=module.row_delta_metrics(metrics=metrics,cursor_metrics=[],labels=['a','b'],required_needles={'marker'})
            self.assertTrue(module.row_delta_anomalies(deltas,max_row_delta=0))
        rows, anomalies=module.frame_metrics(label='a',frame_index=0,text='marker\nmarker',needles=['marker'],transient_needles=['marker'])
        self.assertEqual(rows[0]['count'],2)
        self.assertEqual(anomalies[0]['kind'],'duplicate_transient')

    def test_required_single_pane_marker_and_optional_idle_policy(self):
        module=sampler('codex')
        for targets,needles,expected in (([],[],2),(['a=one'],['marker'],1),(['a=one'],['idle'],0),(['a=one'],[],0),(['a=one','b=two'],[],0),(['a=one','b=two'],['marker'],1)):
            with self.subTest(targets=targets,needles=needles), tempfile.TemporaryDirectory() as tmp:
                argv=['sampler','--out',str(Path(tmp)/'out'),'--frames','1']
                for target in targets: argv+=['--target',target]
                for needle in needles: argv+=['--needle',needle]
                with mock.patch.object(sys,'argv',argv), mock.patch.object(module,'run_tmux',return_value=b'idle\n'):
                    if expected==2:
                        with self.assertRaises(SystemExit): module.main()
                    else: self.assertEqual(module.main(),expected)

    def test_temporal_markers_may_appear_partway_through_matching_runs(self):
        module=sampler('codex')
        states=['Working...\n','Working...\nHello\n','Hello\n']
        calls={'one':0,'two':0}
        def capture(target, *, ansi, history_start):
            text=states[calls[target]]
            if ansi: calls[target]+=1
            return text
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            argv=['sampler','--out',str(out),'--target','a=one','--target','b=two','--needle','Working...','--needle','Hello','--transient','Working...','--frames','3','--interval','0']
            with mock.patch.object(sys,'argv',argv), mock.patch.object(module,'capture',side_effect=capture), mock.patch.object(module,'run_tmux',return_value=b'0\t0\t1\t2\t0\n'):
                self.assertEqual(module.main(),0)
            self.assertEqual(json.loads((out/'anomalies.json').read_text()),[])
