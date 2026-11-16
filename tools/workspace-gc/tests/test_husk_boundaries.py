"""Synthetic directory substitutions at husk/cache deletion boundaries."""

import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

from workspace_gc import husks
from tests.helpers import ok_signals


class TestHuskIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.path = os.path.join(self.root, 'ws-synthetic')
        for rel in ('.cache/uv', 'node_modules'):
            target = Path(self.path, rel)
            target.mkdir(parents=True)
            (target / 'sentinel').write_text('keep')
        patcher = mock.patch.object(husks, '_now', return_value=time.time() + 100 * 3600)
        patcher.start()
        self.addCleanup(patcher.stop)

    def remove(self):
        return husks._remove_one(husks.Husk(self.path), [self.root], [],
                                 ok_signals(), 0, 0)

    def test_replacement_between_inspection_and_open_is_refused(self):
        for rel in ('', '.cache', '.cache/uv', 'node_modules'):
            for kind in ('directory', 'symlink'):
                with self.subTest(rel=rel, kind=kind):
                    self.path = os.path.join(self.root, f'ws-{len(os.listdir(self.root))}')
                    for payload in ('.cache/uv', 'node_modules'):
                        target = Path(self.path, payload)
                        target.mkdir(parents=True)
                        (target / 'sentinel').write_text('keep')
                    victim = os.path.join(self.path, rel).rstrip('/')
                    old = victim + '-old'
                    other = os.path.join(self.root, 'replacement')
                    real = husks._remove_payloads

                    def swap(*args, **kw):
                        os.rename(victim, old)
                        if kind == 'directory':
                            os.mkdir(victim)
                        else:
                            os.mkdir(other)
                            os.symlink(other, victim)
                        for payload in ('.cache/uv', 'node_modules'):
                            target = Path(self.path, payload)
                            target.mkdir(parents=True, exist_ok=True)
                            (target / 'sentinel').write_text('replacement')
                        Path(victim, 'sentinel').write_text('replacement')
                        return real(*args, **kw)

                    try:
                        with mock.patch.object(husks, '_remove_payloads', side_effect=swap):
                            reason = self.remove()
                        self.assertTrue(reason, 'replacement must cause refusal')
                        self.assertEqual(Path(victim, 'sentinel').read_text(), 'replacement')
                        for payload in ('.cache/uv', 'node_modules'):
                            self.assertTrue(Path(self.path, payload, 'sentinel').exists())
                    finally:
                        if os.path.islink(victim):
                            os.unlink(victim)
                            shutil.rmtree(other)
                        elif os.path.exists(victim):
                            shutil.rmtree(victim)
                        if os.path.exists(old):
                            os.rename(old, victim)

    def test_payload_replaced_after_open_is_refused(self):
        real = os.open
        victim = Path(self.path, '.cache/uv')
        old = Path(self.path, '.cache/uv-old')

        def swap(name, *args, **kw):
            fd = real(name, *args, **kw)
            if name == 'uv':
                victim.rename(old)
                victim.mkdir()
                (victim / 'sentinel').write_text('replacement')
            return fd

        with mock.patch.object(husks.os, 'open', side_effect=swap):
            reason = self.remove()
        self.assertTrue(reason)
        self.assertEqual((victim / 'sentinel').read_text(), 'replacement')
        self.assertTrue((old / 'sentinel').exists())
        self.assertEqual((old / 'sentinel').read_text(), 'keep')
        self.assertTrue(Path(self.path, 'node_modules/sentinel').exists())

    def test_same_generation_cache_removal_leaves_shell(self):
        self.assertEqual(self.remove(), '')
        self.assertTrue(os.path.isdir(self.path))
        self.assertFalse(Path(self.path, '.cache/uv').exists())
        self.assertFalse(Path(self.path, 'node_modules').exists())
