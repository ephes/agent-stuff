import os
from pathlib import Path
from unittest import mock
from tests.helpers import GitFixture, sh, SourceStatus
from workspace_gc import remove, signals


class TestFinalDeletion(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.path = self.clone(self.url, 'ws-final')
        self.co = self.by_path(self.build())[self.path]
        self.assertEqual(self.co.cls, 'A', self.co.reasons)

    def test_replacement_after_recheck_is_never_deleted(self):
        for kind in ('directory', 'symlink'):
            with self.subTest(kind=kind):
                real = remove._recheck_local
                changed = []
                checks = []
                old = self.path + '-original'
                def swap(*a, **kw):
                    result = real(*a, **kw)
                    checks.append(True)
                    if len(checks) != 2:
                        return result
                    os.rename(self.path, old)
                    if kind == 'directory':
                        os.mkdir(self.path)
                    else:
                        other = self.path + '-other'
                        os.mkdir(other)
                        os.symlink(other, self.path)
                    Path(self.path, 'sentinel').write_bytes(b'keep')
                    changed.append(True)
                    return result
                with mock.patch.object(remove, '_recheck_local', side_effect=swap):
                    with self.assertRaisesRegex(remove.Refused, 'replaced since inspection' if kind == 'directory' else 'delete failed'):
                        remove.remove_checkout(self.co, [self.ws], [self.projects], [])
                self.assertTrue(changed)
                self.assertEqual(Path(self.path, 'sentinel').read_bytes(), b'keep')
                if os.path.islink(self.path):
                    os.unlink(self.path)
                else:
                    __import__('shutil').rmtree(self.path)
                os.rename(old, self.path)

    def test_local_changes_during_remote_verification_refuse_removal(self):
        for change in ('untracked', 'branch', 'stash', 'head'):
            with self.subTest(change=change):
                path = self.clone(self.url, 'ws-' + change)
                co = self.by_path(self.build())[path]
                real = remove._recheck_remote
                changed = []
                def remote(*a, **kw):
                    real(*a, **kw)
                    if change == 'untracked':
                        Path(path, 'new-data').write_bytes(b'keep')
                    elif change == 'branch':
                        sh('git', 'branch', 'new-side-branch', cwd=path)
                    elif change == 'stash':
                        Path(path, 'README.md').write_bytes(b'keep')
                        sh('git', 'stash', 'push', '-m', 'synthetic', cwd=path)
                    else:
                        sh('git', 'commit', '--allow-empty', '-qm', 'new head', cwd=path)
                    changed.append(True)
                with mock.patch.object(remove, '_recheck_remote', side_effect=remote):
                    with self.assertRaisesRegex(remove.Refused, {'untracked':'dirty now', 'branch':'refs moved', 'stash':'stash present', 'head':'refs moved'}[change]):
                        remove.remove_checkout(co, [self.ws], [self.projects], [])
                self.assertTrue(changed)
                self.assertTrue(os.path.isdir(path))
                if change == 'untracked': self.assertEqual(Path(path, 'new-data').read_bytes(), b'keep')

    def test_sibling_worktree_commit_does_not_block_target_removal(self):
        main = self.main_checkout(self.url)
        target = self.worktree(main, 'ws-target', 'target')
        sibling = self.worktree(main, 'ws-sibling', 'sibling')
        co = self.by_path(self.build())[target]
        real = remove._recheck_remote
        changed = []
        def remote(*a, **kw):
            real(*a, **kw)
            self.commit(sibling)
            changed.append(True)
        with mock.patch.object(remove, '_recheck_remote', side_effect=remote):
            outcome = remove.remove_checkout(co, [self.ws], [self.projects], [])
        self.assertTrue(changed)
        self.assertIn('removed worktree', outcome)
        self.assertFalse(os.path.exists(target))
        self.assertTrue(os.path.isdir(sibling))
