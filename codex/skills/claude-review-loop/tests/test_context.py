import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from claude_review_loop import bundle
from tests.test_bundle import git


class TestExplicitContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'user.name', 'test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'commit', '--allow-empty', '-qm', 'initial')
        self.parent = self.root / 'context'
        self.parent.mkdir()
        self.source = self.parent / 'input'
        self.source.write_bytes(b'good')

    def build(self, cap=4, paths=None):
        return bundle.build_bundle(str(self.repo), str(self.root / 'bundle.md'),
            max_file_size=100, max_diff_bytes_per_file=100,
            max_bundle_bytes=10000, max_context_file_size=cap,
            context_files=paths or [str(self.source)])

    def test_context_swap_or_growth_is_fatal(self):
        for kind in ('link', 'fifo', 'ancestor', 'regular', 'growth'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                parent = Path(temp).resolve() / 'parent'
                parent.mkdir()
                self.source = parent / 'input'
                self.source.write_bytes(b'good')
                real = os.lstat
                changed = []
                def swap(path, *a, **kw):
                    info = real(path, *a, **kw)
                    if os.fspath(path) == str(self.source) and not changed:
                        changed.append(True)
                        if kind == 'ancestor':
                            parent.rename(parent.with_name('old'))
                            other = parent.with_name('outside')
                            other.mkdir()
                            (other / 'input').write_bytes(b'leak')
                            parent.symlink_to(other)
                        elif kind == 'growth':
                            with self.source.open('ab') as fh:
                                fh.write(b'overflow')
                        else:
                            self.source.rename(parent / 'old')
                            if kind == 'link':
                                outside = parent / 'outside'
                                outside.write_bytes(b'leak')
                                self.source.symlink_to(outside)
                            elif kind == 'fifo':
                                os.mkfifo(self.source)
                            else:
                                self.source.write_bytes(b'leak')
                    return info
                real_open = open
                def safe_open(path, *a, **kw):
                    if kind == 'fifo' and os.fspath(path) == str(self.source):
                        raise AssertionError('blocking FIFO open')
                    return real_open(path, *a, **kw)
                real_os_open = os.open
                def safe_os_open(path, flags, *a, **kw):
                    if kind == 'fifo' and os.path.basename(os.fspath(path)) == 'input':
                        self.assertTrue(flags & os.O_NONBLOCK, 'blocking FIFO open')
                    return real_os_open(path, flags, *a, **kw)
                with mock.patch.object(os, 'lstat', swap), mock.patch('builtins.open', safe_open), mock.patch.object(os, 'open', safe_os_open):
                    with self.assertRaises(OSError):
                        self.build()
                self.assertTrue(changed)
                self.assertFalse((self.root / 'bundle.md').exists())

    def test_exact_utf8_byte_cap_and_multiple_contexts(self):
        self.source.write_bytes('éé'.encode())
        second = self.parent / 'second'
        second.write_bytes(b'test')
        result = self.build(paths=[str(self.source), str(second)])
        text = Path(result.path).read_text(encoding='utf-8')
        self.assertIn('éé', text)
        self.assertIn('Review context: [2]', text)
        with self.assertRaises(OSError):
            self.build(cap=3)
