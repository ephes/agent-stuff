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
                    with mock.patch.object(sys,'argv',['sampler','--out',str(out),'--target','a=one','--frames','1','--interval',interval]), mock.patch.object(module,'run_tmux',side_effect=lambda args: b'0\t0\t1\t1\t0\n' if args[0]=='display-message' else b'Working...\n'):
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
                with mock.patch.object(sys,'argv',argv), mock.patch.object(module,'run_tmux',side_effect=lambda args: b'0\t0\t1\t1\t0\n' if args[0]=='display-message' else b'idle\n'):
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

class TestFrameCoordinates(unittest.TestCase):
    def test_viewport_coordinates_ignore_history_and_pane_height(self):
        module=sampler('codex')
        for shift in (0,1):
            metrics=[{'label':'a','frame':0,'needle':'marker','rows':'102','count':1},
                     {'label':'b','frame':0,'needle':'marker','rows':str(7+shift),'count':1}]
            cursors=[{'label':'a','frame':0,'cursor_y':2,'capture_origin':-100,'pane_height':10},
                     {'label':'b','frame':0,'cursor_y':2+shift,'capture_origin':-5,'pane_height':8}]
            rows=module.row_delta_metrics(metrics=metrics,cursor_metrics=cursors,labels=['a','b'])
            self.assertEqual([row['delta'] for row in rows],[shift,shift])
            self.assertEqual(bool(module.row_delta_anomalies(rows,max_row_delta=0)),bool(shift))
        metrics[1]['rows']='7'
        cursors[1]['cursor_y']=None
        cursors[0]['cursor_y']=None
        rows=module.row_delta_metrics(metrics=metrics,cursor_metrics=cursors,labels=['a','b'])
        cursor=next(row for row in rows if row['kind']=='cursor')
        self.assertIsNone(cursor['delta']); self.assertIsNone(cursor['reference_row'])
        self.assertFalse(module.row_delta_anomalies(rows,max_row_delta=0))

    def test_cursor_metadata_and_physical_row_capture(self):
        module=sampler('codex')
        with mock.patch.object(module,'run_tmux',return_value=b'3\t4\t1\t25\t100\n'):
            cursor=module.cursor_position('synthetic')
        self.assertEqual(cursor['pane_height'],25); self.assertEqual(cursor['history_size'],100)
        with mock.patch.object(module,'run_tmux',return_value=b'?\t?\t0\t?\t?\n'):
            cursor=module.cursor_position('synthetic')
        self.assertIsNone(cursor['cursor_y'])
        with mock.patch.object(module,'run_tmux',return_value=b'physical row\n') as run:
            module.capture('synthetic',ansi=True,history_start='-500')
        self.assertNotIn('-J',run.call_args.args[0])

    def test_main_uses_one_ansi_payload_and_records_sampling_uncertainty(self):
        module=sampler('codex')
        payload='\x1b[31mmarker λ\x1b[0m\n\n'
        def changing_capture(target, *, ansi, history_start):
            return payload if ansi else 'contradictory old redraw\n'
        cursor={'cursor_x':0,'cursor_y':0,'pane_active':True,'pane_height':2,'history_size':3}
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with mock.patch.object(sys,'argv',['sampler','--out',str(out),'--target','a=one','--needle','marker','--frames','1']), mock.patch.object(module,'capture',side_effect=changing_capture) as capture, mock.patch.object(module,'cursor_position',return_value=cursor):
                self.assertEqual(module.main(),0)
            self.assertEqual(capture.call_count,1)
            self.assertTrue(capture.call_args.kwargs['ansi'])
            self.assertEqual((out/'frames/a-00.log').read_text(encoding='utf-8'),'marker λ\n\n')
            self.assertEqual((out/'frames/a-00.ansi').read_text(encoding='utf-8'),payload)
            metrics=json.loads((out/'frame-metrics.json').read_text())
            self.assertEqual(next(row for row in metrics if row['needle']=='marker')['count'],1)
            info=json.loads((out/'cursor-metrics.json').read_text())[0]
            self.assertFalse(info['cursor_atomic'])
            self.assertLessEqual(info['capture_started_s'],info['capture_finished_s'])
            self.assertLessEqual(info['capture_finished_s'],info['cursor_started_s'])
            self.assertLessEqual(info['cursor_started_s'],info['cursor_finished_s'])
            self.assertEqual(info['capture_origin'],0)

    def test_history_only_marker_does_not_satisfy_reference_evidence(self):
        module=sampler('codex')
        payload='marker\nhistory\nhistory\nidle\n\n'
        cursor={'cursor_x':0,'cursor_y':0,'pane_active':True,'pane_height':2,'history_size':3}
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with mock.patch.object(sys,'argv',['sampler','--out',str(out),'--target','a=one','--needle','marker','--frames','1']), mock.patch.object(module,'capture',return_value=payload), mock.patch.object(module,'cursor_position',return_value=cursor):
                self.assertEqual(module.main(),1)
            self.assertEqual(json.loads((out/'anomalies.json').read_text())[0]['kind'],'missing_marker')

    def test_unavailable_basis_is_not_misreported_as_a_missing_marker(self):
        module=sampler('codex')
        for targets in (['a=one'],['a=one','b=two']):
            with tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'out'; argv=['sampler','--out',str(out),'--frames','1','--needle','marker']
                for target in targets: argv+=['--target',target]
                def cursor(target):
                    return {'cursor_x':0,'cursor_y':0,'pane_active':True,'pane_height':None if target=='one' else 1,'history_size':0}
                with mock.patch.object(sys,'argv',argv), mock.patch.object(module,'capture',return_value='marker\n'), mock.patch.object(module,'cursor_position',side_effect=cursor):
                    self.assertEqual(module.main(),1)
                anomalies=json.loads((out/'anomalies.json').read_text())
                self.assertEqual([item['kind'] for item in anomalies],['coordinate_basis_unavailable'])

    def test_unicode_separator_is_a_cell_character_not_a_physical_row(self):
        module=sampler('codex')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with mock.patch.object(sys,'argv',['sampler','--out',str(out),'--target','a=one','--needle','marker','--frames','1']), mock.patch.object(module,'capture',return_value='marker\u2028tail\n'), mock.patch.object(module,'cursor_position',return_value={'cursor_x':0,'cursor_y':0,'pane_active':True,'pane_height':1,'history_size':0}):
                self.assertEqual(module.main(),0)

    def test_claude_copy_also_derives_plain_from_one_capture(self):
        module=sampler('claude')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with mock.patch.object(sys,'argv',['sampler','--out',str(out),'--target','a=one','--frames','1']), mock.patch.object(module,'capture',return_value='\x1b[31mWorking...\x1b[0m\n') as capture:
                self.assertEqual(module.main(),0)
            self.assertEqual(capture.call_count,1)
            self.assertEqual((out/'frames/a-00.log').read_text(),'Working...\n')
