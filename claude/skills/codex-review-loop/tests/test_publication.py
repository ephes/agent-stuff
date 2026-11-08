import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from codex_review_loop import result


class TestPublication(unittest.TestCase):
    def make(self, **kw):
        return result.ReviewResult(state='CLEAN', items=[], model='synthetic',
            cost=None, started_at=1, ended_at=2, **kw)

    def test_serialization_errors_preserve_previous_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            path.write_text('{"previous":true}', encoding='utf-8')
            for value in ({'nested': object()}, float('nan'), float('inf'), -float('inf')):
                receipt = self.make()
                receipt.items = [value]
                with self.subTest(value=type(value)), self.assertRaises((ValueError, TypeError)):
                    receipt.write(path)
                self.assertEqual(json.loads(path.read_text()), {'previous': True})
                self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_write_flush_replace_and_interrupt_preserve_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            path.write_text('{"previous":true}', encoding='utf-8')
            real_fdopen = result.os.fdopen
            for fault in ('write', 'flush', 'replace', 'interrupt'):
                injected = []
                class FailingFile:
                    def __init__(self, fd, *a, **kw):
                        self.fh = real_fdopen(fd, *a, **kw)
                    def __enter__(self): return self
                    def __exit__(self, *a): self.fh.close()
                    def write(self, text):
                        self.fh.write(text[:3])
                        if fault in ('write', 'interrupt'):
                            injected.append(True)
                            raise KeyboardInterrupt() if fault == 'interrupt' else OSError('write')
                        self.fh.write(text[3:])
                    def flush(self):
                        if fault == 'flush':
                            injected.append(True)
                            raise OSError('flush')
                        self.fh.flush()
                def replace(*a):
                    injected.append(True)
                    raise OSError('replace')
                with self.subTest(fault=fault), mock.patch.object(result.os, 'fdopen', FailingFile), mock.patch.object(result.os, 'replace', side_effect=replace):
                    with self.assertRaises((OSError, KeyboardInterrupt)):
                        self.make().write(path)
                self.assertTrue(injected)
                self.assertEqual(json.loads(path.read_text()), {'previous': True})
                self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_unicode_and_optional_fields_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            receipt = self.make(error='λ')
            receipt.write(path)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), receipt.to_dict())

    def test_nonfinite_cost_and_duration_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            for field in ('cost', 'started_at', 'ended_at'):
                for value in (float('nan'), float('inf')):
                    receipt = self.make()
                    setattr(receipt, field, value)
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        receipt.write(path)
                    self.assertFalse(path.exists())
                    self.assertEqual(list(Path(tmp).iterdir()), [])
