import os
import unittest
from unittest import mock

from codex_review_loop import env, lock


class TestEnv(unittest.TestCase):
    def test_codex_home_is_pinned_not_inherited(self):
        built = env.codex_env(base={"CODEX_HOME": "/elsewhere", "PATH": "/bin",
                                    "OPENAI_BASE_URL": "http://proxy"})
        self.assertEqual(built["CODEX_HOME"], os.path.expanduser("~/.codex"))
        self.assertNotIn("OPENAI_BASE_URL", built)
        self.assertEqual(built["PATH"], "/bin")

    def test_only_allowlisted_variables_pass(self):
        built = env.codex_env(base={"PATH": "/bin", "AWS_SECRET_ACCESS_KEY": "x",
                                    "GITHUB_TOKEN": "y", "HOME": "/h"})
        self.assertEqual(set(built), {"PATH", "HOME", "CODEX_HOME"})

    def test_deliberate_override(self):
        built = env.codex_env(base={"CODEX_REVIEW_HOME": "/review-home"})
        self.assertEqual(built["CODEX_HOME"], "/review-home")


class TestPgidIdentity(unittest.TestCase):
    def check(self, command):
        completed = mock.Mock(stdout=command)
        with mock.patch("subprocess.run", return_value=completed):
            return lock._pgid_is_codex(4242)

    def test_launcher_and_binary_are_recognised(self):
        self.assertTrue(self.check("node /opt/homebrew/bin/codex -a never exec\n"))
        self.assertTrue(self.check("/usr/local/bin/codex exec\n"))

    def test_anything_else_is_not_killed(self):
        self.assertFalse(self.check("python3 server.py\n"))
        self.assertFalse(self.check(""))
        self.assertFalse(lock._pgid_is_codex(1))
        self.assertEqual(lock.DEFAULT_MAX_CONCURRENT, 10)


if __name__ == "__main__":
    unittest.main()
