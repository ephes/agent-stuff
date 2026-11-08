import unittest
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


class TestGitWrapper(unittest.TestCase):
    def setUp(self):
        self.saved = git._base_env
        git._base_env = {'GIT_OPTIONAL_LOCKS':'0', 'GIT_TERMINAL_PROMPT':'0'}
        self.addCleanup(setattr, git, '_base_env', self.saved)

    def test_owned_group_is_terminated_and_reaped_on_timeout_or_interrupt(self):
        import signal
        import subprocess
        for fault in (subprocess.TimeoutExpired('git',1), KeyboardInterrupt()):
            proc = mock.MagicMock(pid=4242,returncode=None)
            proc.__enter__.return_value = proc
            proc.communicate.side_effect = [fault, ('','')]
            with self.subTest(fault=type(fault).__name__), mock.patch.object(git.subprocess,'Popen',return_value=proc) as popen, mock.patch.object(git.os,'killpg') as kill:
                if isinstance(fault, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt): git.run(['status'],timeout=1)
                else:
                    with self.assertRaisesRegex(git.GitError,'timed out'): git.run(['status'],timeout=1)
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
            self.assertEqual(kill.call_args_list,[mock.call(4242,signal.SIGTERM),mock.call(4242,signal.SIGKILL)])
            self.assertEqual(proc.communicate.call_count,1)
            proc.wait.assert_called_once_with(timeout=1)

    def test_argv_alternates_and_failure_diagnostics(self):
        from subprocess import CompletedProcess
        proc = mock.MagicMock(returncode=1)
        proc.__enter__.return_value = proc
        proc.communicate.return_value = ('', 'first line\n' + 'x'*2000)
        cwd='/synthetic/path with spaces'
        with mock.patch.object(git.subprocess,'Popen',return_value=proc) as popen:
            with self.assertRaises(git.GitError) as caught:
                git.run(['show','argument with spaces'],cwd,alternates=['/synthetic/object dir'])
        self.assertLess(len(str(caught.exception)),700)
        cmd=popen.call_args.args[0]
        self.assertEqual(cmd[-2:], ['show','argument with spaces'])
        self.assertEqual(cmd[cmd.index('-C')+1],cwd)
        self.assertIn('core.fsmonitor=false',cmd)
        self.assertIn('core.untrackedCache=false',cmd)
        self.assertEqual(popen.call_args.kwargs['env']['GIT_ALTERNATE_OBJECT_DIRECTORIES'],'/synthetic/object dir')
        self.assertNotIn('GIT_ALTERNATE_OBJECT_DIRECTORIES',git.base_env())
        proc.returncode=0
        proc.communicate.return_value=('safe','')
        with mock.patch.object(git.subprocess,'Popen',return_value=proc) as popen:
            result=git.run(['status'])
        self.assertEqual(result.stdout,'safe')
        self.assertNotIn('GIT_ALTERNATE_OBJECT_DIRECTORIES',popen.call_args.kwargs['env'])

    def test_concurrent_environment_copies_cannot_mutate_cached_state(self):
        from concurrent.futures import ThreadPoolExecutor
        def mutate(i):
            env=git.base_env()
            env['GIT_OPTIONAL_LOCKS']=str(i+1)
            env['private']=str(i)
            return env
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(mutate,range(12)))
        self.assertEqual(len({id(env) for env in results}),12)
        self.assertEqual(git.base_env()['GIT_OPTIONAL_LOCKS'],'0')
        self.assertNotIn('private',git.base_env())

    def test_zombie_group_errors_preserve_original_and_still_reap(self):
        import subprocess
        for fault in (subprocess.TimeoutExpired('git',1), KeyboardInterrupt()):
            proc=mock.MagicMock(pid=4242,returncode=None)
            proc.communicate.side_effect=fault
            with mock.patch.object(git.subprocess,'Popen',return_value=proc), mock.patch.object(git.os,'killpg',side_effect=PermissionError('synthetic zombie group')):
                if isinstance(fault,KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt): git.run(['status'],timeout=1)
                else:
                    with self.assertRaisesRegex(git.GitError,'timed out'): git.run(['status'],timeout=1)
            proc.wait.assert_called_once_with(timeout=1)
            self.assertEqual(proc.communicate.call_count,1)

    def test_real_transport_descendant_gets_graceful_cleanup(self):
        import shlex, signal, sys, tempfile, time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); helper=root/'helper.py'; pids=root/'pids'; receipt=root/'reaped'
            helper.write_text("""import os, signal, subprocess, sys, time
from pathlib import Path
root=Path(sys.argv[1])
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
def stop(*args):
    child.terminate()
    child.wait(timeout=1)
    (root/'reaped').write_text('reaped')
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
(root/'pids').write_text(str(os.getpid())+' '+str(child.pid))
time.sleep(30)
""",encoding='utf-8')
            git._base_env.update(PATH=os.environ['PATH'],GIT_CONFIG_GLOBAL=os.devnull,
                GIT_CONFIG_NOSYSTEM='1',GIT_SSH_VARIANT='ssh',
                GIT_SSH_COMMAND=shlex.join([sys.executable,str(helper),str(root)]))
            try:
                with self.assertRaisesRegex(git.GitError,'timed out'):
                    git.run(['ls-remote','ssh://synthetic.invalid/repo'],timeout=1)
                self.assertTrue(pids.exists(),'synthetic transport did not start')
                self.assertEqual(receipt.read_text(),'reaped')
                _, descendant=map(int,pids.read_text().split())
                with self.assertRaises(ProcessLookupError): os.kill(descendant,0)
            finally:
                if pids.exists():
                    for pid in map(int,pids.read_text().split()):
                        try: os.kill(pid,signal.SIGTERM)
                        except ProcessLookupError: pass

    def test_check_false_returns_failed_command_without_signalling(self):
        proc=mock.MagicMock(returncode=7)
        proc.communicate.return_value=('synthetic output','synthetic failure')
        with mock.patch.object(git.subprocess,'Popen',return_value=proc), mock.patch.object(git.os,'killpg') as kill:
            result=git.run(['status'],check=False)
        self.assertEqual(result.returncode,7)
        self.assertEqual(result.stdout,'synthetic output')
        self.assertEqual(result.stderr,'synthetic failure')
        kill.assert_not_called()
