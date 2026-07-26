import os
import unittest
from unittest import mock

from pi_review_loop import env


class TestPiEnv(unittest.TestCase):
    def test_strips_inherited_cross_workspace_agent_dir(self):
        base = {"PATH": "/usr/bin", "PI_CODING_AGENT_DIR": "/Users/x/.config/emerge"}
        out = env.pi_env(base=base)
        self.assertNotEqual(out["PI_CODING_AGENT_DIR"], "/Users/x/.config/emerge")
        self.assertEqual(
            out["PI_CODING_AGENT_DIR"], os.path.expanduser(env.DEFAULT_AGENT_DIR)
        )

    def test_strips_inherited_codex_home(self):
        base = {"PATH": "/usr/bin", "CODEX_HOME": "/Users/x/.config/emerge"}
        self.assertNotIn("CODEX_HOME", env.pi_env(base=base))

    def test_preserves_unrelated_environment(self):
        base = {"PATH": "/usr/bin", "HOME": "/Users/x", "LANG": "en_US.UTF-8"}
        out = env.pi_env(base=base)
        self.assertEqual(out["PATH"], "/usr/bin")
        self.assertEqual(out["LANG"], "en_US.UTF-8")

    def test_applies_harness_defaults(self):
        out = env.pi_env(base={})
        self.assertEqual(out["PI_SKIP_VERSION_CHECK"], "1")
        self.assertEqual(out["PI_TELEMETRY"], "0")

    def test_deliberate_override_wins_over_pinned_default(self):
        base = {
            "PI_CODING_AGENT_DIR": "/stale/from/another/workspace",
            "PI_REVIEW_AGENT_DIR": "/explicit/review/agent",
        }
        out = env.pi_env(base=base)
        self.assertEqual(out["PI_CODING_AGENT_DIR"], "/explicit/review/agent")

    def test_caller_overrides_win(self):
        out = env.pi_env({"PI_TELEMETRY": "1"}, base={})
        self.assertEqual(out["PI_TELEMETRY"], "1")

    def test_defaults_to_process_environment(self):
        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": "/stale"}, clear=False):
            out = env.pi_env()
        self.assertEqual(
            out["PI_CODING_AGENT_DIR"], os.path.expanduser(env.DEFAULT_AGENT_DIR)
        )


class TestModelPreflightIsolation(unittest.TestCase):
    def test_list_models_does_not_inherit_stale_agent_dir(self):
        from pi_review_loop import model

        captured = {}

        def fake_run(cmd, **kwargs):
            captured.update(kwargs)
            return mock.Mock(returncode=0, stdout="openai-codex/gpt-5.6-sol\n", stderr="")

        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": "/stale"}, clear=False):
            with mock.patch("pi_review_loop.model.subprocess.run", fake_run):
                model.ensure_model_available("openai-codex/gpt-5.6-sol")

        self.assertEqual(
            captured["env"]["PI_CODING_AGENT_DIR"],
            os.path.expanduser(env.DEFAULT_AGENT_DIR),
        )


if __name__ == "__main__":
    unittest.main()
