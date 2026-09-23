import os
import tempfile
import tomllib
import unittest

from codex_review_loop import command


class TestCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "review-root")
        os.mkdir(self.root)
        self.cmd = command.codex_cmd(
            codex_bin="codex", review_root=self.root, schema_path="/s.json",
            last_message_path="/m.json", instruction='Say "hi"\nthen \\ stop')

    def tearDown(self):
        self.tmp.cleanup()

    def overrides(self):
        return [self.cmd[i + 1] for i, a in enumerate(self.cmd) if a == "-c"]

    def test_every_override_is_valid_toml(self):
        for override in self.overrides():
            with self.subTest(override=override):
                tomllib.loads(override)

    def test_instruction_round_trips(self):
        parsed = tomllib.loads([o for o in self.overrides()
                                if o.startswith("developer_instructions=")][0])
        self.assertEqual(parsed["developer_instructions"], 'Say "hi"\nthen \\ stop')

    def test_filesystem_grants_only_the_review_root(self):
        text = [o for o in self.overrides() if ".filesystem=" in o][0]
        fs = tomllib.loads(text)["permissions"][command.PROFILE_NAME]["filesystem"]
        self.assertEqual(fs, {
            ":minimal": "read",
            "/tmp": "deny", "/private/tmp": "deny", "/private/var/folders": "deny",
            os.path.realpath(self.root): "read",
        })

    def test_pins_model_effort_profile_and_stdin(self):
        c = self.cmd
        self.assertEqual(c[:4], ["codex", "-a", "never", "exec"])
        self.assertEqual(c[c.index("-m") + 1], "gpt-6-sol")
        self.assertEqual(c[-1], "-")
        self.assertIn('model_reasoning_effort="medium"', self.overrides())
        self.assertIn(f'default_permissions="{command.PROFILE_NAME}"', self.overrides())
        self.assertIn(f"permissions.{command.PROFILE_NAME}.network.enabled=false",
                      self.overrides())
        self.assertIn("agents.enabled=false", self.overrides())
        self.assertIn('shell_environment_policy.inherit="core"', self.overrides())
        for flag in ("--ignore-user-config", "--ignore-rules", "--json"):
            self.assertIn(flag, c)
        self.assertNotIn("--sandbox", c)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", c)

    def test_effort_is_selectable_but_only_from_the_list(self):
        kw = dict(codex_bin="codex", review_root=self.root, schema_path="s.json",
                  last_message_path="m.json", instruction="x")
        cmd = command.codex_cmd(effort="medium", **kw)
        self.assertIn('model_reasoning_effort="medium"', cmd)
        with self.assertRaises(ValueError):
            command.codex_cmd(effort="low", **kw)

    def test_disables_every_listed_feature(self):
        disabled = {self.cmd[i + 1] for i, a in enumerate(self.cmd) if a == "--disable"}
        self.assertEqual(disabled, set(command.DISABLED_FEATURES))
        for feature in ("apps", "multi_agent", "plugins", "image_generation",
                        "unbounded_connection_retries"):
            self.assertIn(feature, disabled)
        self.assertNotIn("code_mode_host", disabled)


if __name__ == "__main__":
    unittest.main()
