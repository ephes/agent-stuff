import os
from pathlib import Path
from unittest import mock
from tests.helpers import GitFixture, sh
from workspace_gc import git, inventory


class TestGitEnvironment(GitFixture):
    def test_repository_and_config_injection_is_removed(self):
        url = self.network_repo()
        repo = self.clone(url, 'ws-original')
        other = self.clone(url, 'ws-other')
        self.commit(other)
        expected = sh('git', 'rev-parse', 'HEAD', cwd=repo).strip()
        injected = {'GIT_COMMON_DIR': str(Path(other)/'.git'),
                    'GIT_OBJECT_DIRECTORY': str(Path(other)/'.git/objects'),
                    'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.worktree',
                    'GIT_CONFIG_VALUE_0': other, 'GIT_CONFIG_PARAMETERS': "'core.bare=true'",
                    'GIT_NAMESPACE': 'synthetic'}
        with mock.patch.dict(os.environ, {**injected, 'PATH':os.environ['PATH'], 'GIT_CONFIG_GLOBAL':os.environ['GIT_CONFIG_GLOBAL'], 'GIT_CONFIG_NOSYSTEM':'1'}, clear=True):
            git._base_env = None
            env = git.base_env()
            for key in injected: self.assertFalse(key in env, key)
            self.assertEqual(git.out(['rev-parse','HEAD'],repo).strip(), expected)
            self.write(repo, 'new-data', 'dirty')
            self.assertIn('new-data', git.out(['status','--porcelain','-uall'], repo))
        git._base_env = None

    def test_local_file_urls_and_plain_paths(self):
        directory = Path(self.tmp) / 'space λ # %20'
        directory.mkdir()
        for url in (directory.as_uri(), directory.as_uri().replace('file:///', 'file://localhost/')):
            self.assertEqual(git.local_url_path(url, self.tmp), str(directory))
        self.assertEqual(git.local_url_path('./colon:name', self.tmp), str(Path(self.tmp)/'colon:name'))
        for url in ('file://remote.example/tmp/repo', 'file:///tmp/repo?query=1', 'file:///tmp/repo#fragment', 'file:////srv/repo', 'file:///tmp/%FF', 'file:///tmp/%00x'):
            with self.assertRaises(git.GitError): git.local_url_path(url, self.tmp)

    def test_percent_encoded_local_remote_chain_resolves(self):
        url = self.network_repo()
        sibling = self.clone(url, 'ws-space λ')
        leaf = self.clone(sibling, 'ws-leaf')
        sh('git','remote','set-url','origin',Path(sibling).as_uri(),cwd=leaf)
        inspector = inventory.Inspector([self.projects],use_cache=False)
        try:
            urls, alternates, _ = inspector.resolve_remotes(leaf)
        finally:
            inspector.close()
        self.assertIn(url,urls)
        self.assertIn(str(Path(sibling)/'.git/objects'),alternates)
