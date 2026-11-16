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


class SyntheticWorkspace(unittest.TestCase):
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


class TestHuskIdentity(SyntheticWorkspace):
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


class TestHuskDeviceBoundary(SyntheticWorkspace):
    """Inject device identities without mounting or accessing real storage."""

    def foreign_stat(self, st):
        values = list(st)
        values[2] = st.st_dev + 1
        return os.stat_result(values)

    def test_inspection_refuses_foreign_child_without_descending(self):
        real = os.lstat
        foreign = Path(self.path, '.cache/uv')

        def different_device(path, *args, **kw):
            st = real(path, *args, **kw)
            if os.fspath(path).rstrip('/') == str(foreign):
                return self.foreign_stat(st)
            return st

        with mock.patch.object(husks.os, 'lstat', side_effect=different_device), \
                mock.patch.object(husks.os, 'scandir', wraps=os.scandir) as scanned, \
                mock.patch.object(husks, '_du_kb', return_value=1) as size:
            h = husks.inspect(self.path)
            husks._classify(h, 0, 1)
        self.assertIn('device', h.note)
        self.assertFalse(h.removable)
        self.assertFalse(h.stale)
        size.assert_not_called()
        self.assertNotIn(mock.call(str(foreign)), scanned.call_args_list)
        self.assertTrue((foreign / 'sentinel').exists())

    def test_late_boundary_refuses_whole_candidate_before_mutation(self):
        for whole in (False, True):
            for fault in ('device', 'unreadable', 'walk-error'):
                with self.subTest(whole=whole, fault=fault):
                    foreign = Path(self.path, 'node_modules/nested')
                    foreign.mkdir(exist_ok=True)
                    (foreign / 'data').write_text('keep')
                    identity = (foreign.stat().st_dev, foreign.stat().st_ino)
                    real = os.fstat
                    scandir = os.scandir

                    def scan(fd):
                        if (fault == 'walk-error' and isinstance(fd, int)
                                and (real(fd).st_dev, real(fd).st_ino) == identity):
                            raise PermissionError('synthetic unreadable directory')
                        return scandir(fd)

                    def changed(fd):
                        st = real(fd)
                        if fault != 'walk-error' and (st.st_dev, st.st_ino) == identity:
                            if fault == 'unreadable':
                                raise PermissionError('synthetic unreadable boundary')
                            return self.foreign_stat(st)
                        return st

                    with mock.patch.object(husks.os, 'fstat', side_effect=changed), \
                            mock.patch.object(husks.os, 'scandir', side_effect=scan), \
                            mock.patch.object(husks.readonly, 'unlock') as unlock, \
                            mock.patch.object(husks, '_empty') as empty, \
                            mock.patch.object(husks.os, 'chmod') as chmod:
                        reason = husks._remove_payloads(
                            self.path, self.root, ['.cache/uv', 'node_modules'] if not whole else [],
                            whole=whole, unlock=True)
                    self.assertTrue(reason, 'late boundary must refuse the candidate')
                    unlock.assert_not_called()
                    empty.assert_not_called()
                    chmod.assert_not_called()
                    self.assertEqual((foreign / 'data').read_text(), 'keep')
                    self.assertTrue(Path(self.path, '.cache/uv/sentinel').exists())
