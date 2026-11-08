import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from codex_review_loop import evidence


class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'input.txt'
        self.source.write_bytes(b'good')
        self.dest = self.root / 'review'
        self.dest.mkdir()

    def copy(self, cap=4):
        return evidence.copy_evidence([str(self.source)], str(self.dest), max_size=cap)

    def test_replaced_final_component_is_refused(self):
        for kind in ('link', 'fifo', 'regular'):
            with self.subTest(kind=kind):
                self.source.unlink(missing_ok=True)
                self.source.write_bytes(b'good')
                real = os.lstat
                changed = []
                def swap(path, *a, **kw):
                    info = real(path, *a, **kw)
                    if os.fspath(path) == str(self.source) and not changed:
                        changed.append(True)
                        self.source.rename(self.root / ('old-' + kind))
                        if kind == 'link':
                            secret = self.root / 'outside'
                            secret.write_bytes(b'leak')
                            self.source.symlink_to(secret)
                        elif kind == 'fifo':
                            os.mkfifo(self.source)
                        else:
                            self.source.write_bytes(b'leak')
                    return info
                real_open = open
                def safe_open(path, *a, **kw):
                    if kind == 'fifo' and os.fspath(path) == str(self.source):
                        raise AssertionError('path-based FIFO open')
                    return real_open(path, *a, **kw)
                with mock.patch.object(os, 'lstat', swap), mock.patch('builtins.open', safe_open):
                    with self.assertRaises(OSError):
                        self.copy()
                self.assertTrue(changed)

    def test_replaced_ancestor_is_refused(self):
        parent = self.root / 'parent'
        parent.mkdir()
        self.source.rename(parent / 'input.txt')
        self.source = parent / 'input.txt'
        other = self.root / 'other'
        other.mkdir()
        (other / 'input.txt').write_bytes(b'leak')
        real = os.lstat
        changed = []
        def swap(path, *a, **kw):
            info = real(path, *a, **kw)
            if os.fspath(path) == str(self.source) and not changed:
                changed.append(True)
                parent.rename(self.root / 'old')
                parent.symlink_to(other, target_is_directory=True)
            return info
        with mock.patch.object(os, 'lstat', swap):
            with self.assertRaises(OSError):
                self.copy()
        self.assertTrue(changed)

    def test_growth_after_stat_is_refused(self):
        real = os.lstat
        changed = []
        def grow(path, *a, **kw):
            info = real(path, *a, **kw)
            if os.fspath(path) == str(self.source) and not changed:
                changed.append(True)
                with self.source.open('ab') as fh:
                    fh.write(b'overflow')
            return info
        with mock.patch.object(os, 'lstat', grow):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                self.copy()
        self.assertTrue(changed)

    def test_exact_byte_cap_and_utf8(self):
        self.source.write_bytes('éé'.encode())
        entries, _ = self.copy()
        self.assertEqual((self.dest / entries[0]['file']).read_bytes(), 'éé'.encode())
        self.dest = self.root / 'second'
        self.dest.mkdir()
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            self.copy(cap=3)

    def test_search_only_ancestor_fallback_is_identity_checked(self):
        from codex_review_loop._shared import bundle
        for changed in (False, True):
            self.dest = self.root / f'fallback-{changed}'
            self.dest.mkdir()
            def denied(*a):
                if changed:
                    self.source.rename(self.root / 'before-fallback')
                    self.source.write_bytes(b'leak')
                raise PermissionError('search-only ancestor')
            with mock.patch.object(bundle, '_open_within_repo', side_effect=denied) as opened:
                if changed:
                    with self.assertRaisesRegex(OSError, 'changed'):
                        self.copy()
                else:
                    entries, _ = self.copy()
                    self.assertEqual((self.dest / entries[0]['file']).read_bytes(), b'good')
            opened.assert_called_once()
