import os
import re
import tempfile
import tomllib
import unittest
from types import SimpleNamespace
from unittest import mock

from codex_review_loop import command


def json_key(path):
    return command.toml_string(os.path.realpath(path)) + "="


class TestCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "review-root")
        os.mkdir(self.root)
        workspace = os.path.join(base, "workspace")
        self.copy = SimpleNamespace(
            root=workspace, path=os.path.join(workspace, "repo"),
            home=os.path.join(workspace, "home"),
            tmp=os.path.join(workspace, "tmp"),
            source_objects="/src/.git/objects")
        self.cmd = command.codex_cmd(
            codex_bin="codex", review_root=self.root, copy=self.copy,
            schema_path="/s.json", last_message_path="/m.json",
            instruction='Say "hi"\nthen \\ stop', toolchain=["/opt/tools"],
            platform="darwin", user_temp=None)

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

    def test_filesystem_grants_the_copy_the_root_and_the_history(self):
        text = [o for o in self.overrides() if ".filesystem=" in o][0]
        fs = tomllib.loads(text)["permissions"][command.PROFILE_NAME]["filesystem"]
        self.assertEqual(fs, {
            ":minimal": "read",
            "/tmp": "deny", "/private/tmp": "deny", "/private/var/folders": "deny",
            "/opt/tools": "read",
            self.root: "read",
            "/src/.git/objects": "read",
            self.copy.root: "write",
        })
        self.assertNotIn(os.path.expanduser("~"), fs)

    def test_linux_denies_no_temporary_directory(self):
        # `:minimal` admits no `/tmp` there, and a deny would drop the read
        # grants for a review root and object store beneath it.
        profile = command.filesystem_profile(
            review_root=self.root, workspace_root=self.copy.root,
            source_objects="/o", codex_bin="/usr/bin/codex",
            toolchain=["/opt/tools"], platform="linux")
        fs = tomllib.loads("fs=" + profile)["fs"]
        self.assertNotIn("deny", fs.values())
        self.assertEqual(fs[self.root], "read")

    def test_reviewer_starts_in_the_copy_with_a_scratch_home(self):
        c = self.cmd
        self.assertEqual(c[c.index("-C") + 1], self.copy.path)
        self.assertIn(f'shell_environment_policy.set.HOME="{self.copy.home}"',
                      self.overrides())
        self.assertIn(f'shell_environment_policy.set.TMPDIR="{self.copy.tmp}"',
                      self.overrides())

    def test_the_copy_is_declared_an_untrusted_project(self):
        # Declared for this invocation only, as a `projects` table: Codex
        # persists trust for an undeclared writable working directory into
        # the user's config, and a dotted override does not stop that.
        tables = [tomllib.loads(o) for o in self.overrides()
                  if o.startswith("projects=")]
        self.assertEqual(tables, [{"projects": {
            os.path.realpath(self.copy.path): {"trust_level": "untrusted"}}}])

    def test_project_trust_quotes_awkward_paths(self):
        override = command.project_trust('/x/a b"c]=.d')
        self.assertEqual(tomllib.loads(override),
                         {"projects": {'/x/a b"c]=.d': {"trust_level": "untrusted"}}})

    def test_only_existing_toolchain_prefixes_are_granted(self):
        profile = command.filesystem_profile(
            review_root=self.root, workspace_root=self.copy.root,
            source_objects="/o", codex_bin="/usr/bin/codex", toolchain=None)
        for path in command.TOOLCHAIN_READ_PATHS:
            self.assertEqual(json_key(path) in profile, os.path.isdir(path))

    def test_default_toolchain_includes_the_codex_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = self._package_install(os.path.realpath(tmp))
            profile = command.filesystem_profile(
                review_root=self.root, workspace_root=self.copy.root,
                source_objects="/o", codex_bin=native, toolchain=None,
                platform="linux")
            root = os.path.join(os.path.realpath(tmp), "installs", "codex",
                                "0.162.1")
        fs = tomllib.loads("fs=" + profile)["fs"]
        self.assertEqual(fs[root], "read")

    @staticmethod
    def _package_install(base):
        """Codex's package layout as mise installs it, behind a `latest` link."""
        root = os.path.join(base, "installs", "codex", "0.162.1")
        os.makedirs(os.path.join(root, "bin"))
        with open(os.path.join(root, command.CODEX_PACKAGE_MANIFEST), "w") as fh:
            fh.write("{}")
        native = os.path.join(root, "bin", "codex")
        open(native, "w").close()
        link = os.path.join(base, "installs", "codex", "latest")
        os.symlink("0.162.1", link)
        return os.path.join(link, "bin", "codex")

    def test_pins_model_effort_profile_and_stdin(self):
        c = self.cmd
        self.assertEqual(c[:4], ["codex", "-a", "never", "exec"])
        self.assertEqual(c[c.index("-m") + 1], "gpt-6.1-sol")
        self.assertEqual(c[-1], "-")
        self.assertIn('model_reasoning_effort="high"', self.overrides())
        self.assertIn(f'default_permissions="{command.PROFILE_NAME}"', self.overrides())
        self.assertIn(f"permissions.{command.PROFILE_NAME}.network.enabled=true",
                      self.overrides())
        self.assertIn("agents.enabled=false", self.overrides())
        self.assertIn('shell_environment_policy.inherit="core"', self.overrides())
        for flag in ("--ignore-user-config", "--ignore-rules", "--json"):
            self.assertIn(flag, c)
        self.assertNotIn("--sandbox", c)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", c)

    def test_effort_is_selectable_but_only_from_the_list(self):
        kw = dict(codex_bin="codex", review_root=self.root, copy=self.copy,
                  schema_path="s.json",
                  last_message_path="m.json", instruction="x")
        cmd = command.codex_cmd(effort="medium", **kw)
        self.assertIn('model_reasoning_effort="medium"', cmd)
        with self.assertRaises(ValueError):
            command.codex_cmd(effort="low", **kw)

    def test_no_access_program_unless_asked_for(self):
        self.assertNotIn("--cyber-access-program", self.cmd)

    def test_access_program_is_passed_with_its_model(self):
        kw = dict(codex_bin="codex", review_root=self.root, copy=self.copy,
                  schema_path="s.json", last_message_path="m.json",
                  instruction="x")
        cmd = command.codex_cmd(access_program="daybreak_blue", **kw)
        self.assertEqual(cmd[cmd.index("--cyber-access-program") + 1],
                         "daybreak_blue")
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-daybreak-blue-latest")
        self.assertEqual(cmd[-1], "-")
        cmd = command.codex_cmd(access_program="standard", **kw)
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-6.1-sol")
        with self.assertRaises(ValueError):
            command.codex_cmd(access_program="daybreak_blue",
                              model="gpt-6.1-sol", **kw)
        with self.assertRaises(ValueError):
            command.codex_cmd(model="gpt-daybreak-blue-latest", **kw)
        with self.assertRaises(ValueError):
            command.codex_cmd(access_program="daybreak", **kw)

    def test_each_program_has_exactly_one_model(self):
        self.assertEqual(command.model_for(None), "gpt-6.1-sol")
        self.assertEqual(command.model_for("standard"), "gpt-6.1-sol")
        self.assertEqual(command.model_for("daybreak_blue"),
                         "gpt-daybreak-blue-latest")
        self.assertEqual(command.model_for("daybreak_red"),
                         "gpt-daybreak-red-latest")

    def test_disables_every_listed_feature(self):
        disabled = {self.cmd[i + 1] for i, a in enumerate(self.cmd) if a == "--disable"}
        self.assertEqual(disabled, set(command.DISABLED_FEATURES))
        for feature in ("apps", "multi_agent", "plugins", "image_generation",
                        "unbounded_connection_retries"):
            self.assertIn(feature, disabled)
        self.assertNotIn("code_mode_host", disabled)



class TestToolchainPaths(unittest.TestCase):
    """The readable toolchain beyond `:minimal`: what Codex and the reviewer's
    tools need on a machine whose software is not all under `/opt/homebrew`
    or `/usr/local` - a Linux host with Codex from mise and uv in
    `~/.local/bin`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.realpath(self.tmp.name)
        self.home = os.path.join(self.base, "home")
        os.mkdir(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def make_file(self, *parts):
        path = os.path.join(self.base, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def package(self, root):
        """A Codex package install under `root`; returns its `latest` link
        to the binary."""
        native = self.make_file(root, "0.162.1", "bin", "codex")
        self.make_file(root, "0.162.1", command.CODEX_PACKAGE_MANIFEST)
        os.symlink("0.162.1", os.path.join(self.base, root, "latest"))
        return os.path.join(self.base, root, "latest", "bin", "codex")

    def paths(self, codex_bin, *, which=lambda name: None, prefixes=(),
              resolv_conf="/nonexistent/resolv.conf", platform="linux"):
        with mock.patch.object(command, "TOOLCHAIN_READ_PATHS", prefixes):
            return command.toolchain_paths(
                codex_bin, which=which, resolv_conf=resolv_conf,
                platform=platform)

    def test_macos_grants_only_the_prefixes(self):
        link = self.package("home/.local/share/mise/installs/codex")
        uv = self.make_file("home", ".local", "bin", "uv")
        self.assertEqual(
            self.paths(link, which={"uv": uv}.get, platform="darwin"), [])

    def test_a_package_install_grants_its_resolved_root(self):
        link = self.package("home/.local/share/mise/installs/codex")
        root = os.path.join(self.home, ".local/share/mise/installs/codex/0.162.1")
        self.assertEqual(self.paths(link), [root])

    def test_a_lone_binary_grants_only_itself(self):
        native = self.make_file("home", ".local", "bin", "codex")
        self.make_file("home", ".local", "bin", "secret-helper")
        self.assertEqual(self.paths(native), [native])

    def test_a_manifest_at_the_home_directory_grants_only_the_binary(self):
        native = self.make_file("home", "bin", "codex")
        self.make_file("home", command.CODEX_PACKAGE_MANIFEST)
        with mock.patch.dict(os.environ, {"HOME": self.home}):
            self.assertEqual(self.paths(native), [native])

    def test_a_tool_binary_on_path_grants_that_file(self):
        native = self.make_file("opt", "codex")
        uv = self.make_file("home", ".local", "bin", "uv")
        self.assertEqual(self.paths(native, which={"uv": uv}.get),
                         [native, uv])

    def test_a_tool_binary_found_on_a_relative_path_is_made_absolute(self):
        native = self.make_file("opt", "codex")
        uv = self.make_file("home", ".local", "bin", "uv")
        cwd = os.getcwd()
        os.chdir(os.path.join(self.home, ".local"))
        try:
            paths = self.paths(native, which={"uv": "bin/uv"}.get)
        finally:
            os.chdir(cwd)
        self.assertEqual(paths, [native, uv])

    def test_a_symlinked_tool_binary_is_not_granted(self):
        # The sandbox would mount only the target, so `uv` would still not
        # be found by name.
        native = self.make_file("opt", "codex")
        uv = self.make_file("home", ".local", "share", "uv-0.13", "uv")
        link = os.path.join(self.home, ".local", "bin", "uv")
        os.makedirs(os.path.dirname(link))
        os.symlink(uv, link)
        self.assertEqual(self.paths(native, which={"uv": link}.get), [native])

    def test_paths_under_a_granted_prefix_are_not_repeated(self):
        prefix = os.path.join(self.base, "brew")
        native = self.make_file("brew", "bin", "codex")
        uv = self.make_file("brew", "bin", "uv")
        self.assertEqual(
            self.paths(native, which={"uv": uv}.get, prefixes=(prefix,)),
            [prefix])

    def test_a_symlinked_resolv_conf_grants_its_target(self):
        native = self.make_file("opt", "codex")
        stub = self.make_file("run", "systemd", "resolve", "stub-resolv.conf")
        conf = os.path.join(self.base, "etc", "resolv.conf")
        os.makedirs(os.path.dirname(conf))
        os.symlink(stub, conf)
        self.assertEqual(self.paths(native, resolv_conf=conf), [native, stub])

    def test_a_plain_resolv_conf_adds_nothing(self):
        native = self.make_file("opt", "codex")
        conf = self.make_file("etc", "resolv.conf")
        self.assertEqual(self.paths(native, resolv_conf=conf), [native])

    def test_nothing_in_the_home_directory_is_granted_wholesale(self):
        link = self.package("home/.local/share/mise/installs/codex")
        uv = self.make_file("home", ".local", "bin", "uv")
        for path in self.paths(link, which={"uv": uv}.get):
            with self.subTest(path=path):
                self.assertNotIn(path, (
                    self.home, os.path.join(self.home, ".local"),
                    os.path.join(self.home, ".local", "bin"),
                    os.path.join(self.home, ".local/share/mise/installs")))


def glob_regex(glob):
    """The Codex glob subset the carve-out uses: `*`, `?`, `[!...]` (a
    leading `-` literal) and a trailing `/**` for the whole subtree."""
    subtree = glob.endswith("/**")
    body = glob[:-3] if subtree else glob
    out, i = "", 0
    while i < len(body):
        c = body[i]
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        elif c == "[":
            end = body.index("]", i)
            chars = body[i + 2:end]
            assert body[i + 1] == "!" and "-" not in chars[1:], glob
            out += "[^/" + re.escape(chars) + "]"
            i = end
        else:
            out += re.escape(c)
        i += 1
    return re.compile(out + ("/.+" if subtree else "") + r"\Z")


class TestPowsyblTempCarveOut(unittest.TestCase):
    T = "/private/var/folders/ab/cd-ef_12/T"

    def classify(self, entries, rel):
        path = f"{self.T}/{rel}"
        denies = [g for g, access in entries if access == "deny"]
        return "deny" if any(glob_regex(g).match(path) for g in denies) else "allow"

    def test_only_itools_names_stay_reachable(self):
        entries = command.powsybl_temp_entries(
            self.T, granted=["/private/tmp/run/workspace", "/src/.git/objects"])
        self.assertEqual(entries[0], (self.T, "write"))
        self.assertEqual({a for _, a in entries[1:]}, {"deny"})
        for rel in ("itools_common_123", "itools_common_1/sub/f", "itools_"):
            with self.subTest(allowed=rel):
                self.assertEqual(self.classify(entries, rel), "allow")
        for rel in ("secret.txt", "dir/nested/secret", ".hidden", "-x", "i",
                    "it", "itools", "itools/x", "itoolsX", "itoolsX/y",
                    "ITOOLS_x", "Itools_x", "tmp.Ab", "tmp.Ab/run/workspace"):
            with self.subTest(denied=rel):
                self.assertEqual(self.classify(entries, rel), "deny")

    def test_no_carve_out_when_a_granted_path_is_inside(self):
        # A deny glob would beat the grant, and carving the run directory out
        # name by name overflows the sandbox compiler, so the temp dir stays
        # denied as a whole.
        for granted in ([f"{self.T}/tmp.Ab/run/workspace"],
                        ["/private/tmp/run/workspace", f"{self.T}/repo/.git/objects"],
                        [self.T]):
            with self.subTest(granted=granted):
                self.assertEqual(
                    command.powsybl_temp_entries(self.T, granted=granted), [])
        profile = command.filesystem_profile(
            codex_bin="codex", platform="darwin",
            review_root=f"{self.T}/tmp.x/run/review-root",
            workspace_root=f"{self.T}/tmp.x/run/workspace",
            source_objects="/o", toolchain=[], user_temp=self.T)
        fs = tomllib.loads("fs=" + profile)["fs"]
        self.assertNotIn(self.T, fs)
        self.assertEqual(fs["/private/var/folders"], "deny")

    def test_fails_closed_on_names_a_glob_could_misread(self):
        for temp in ("/a/T[1]", "/a b/T", "/a/T*", "relative/T", None, ""):
            with self.subTest(temp=temp):
                self.assertEqual(command.powsybl_temp_entries(temp), [])

    def test_profile_detects_the_user_temp_dir_by_default(self):
        with mock.patch.object(command, "darwin_user_temp_dir",
                               return_value=self.T):
            profile = command.filesystem_profile(
                codex_bin="codex", platform="darwin",
                review_root="/r", workspace_root="/w", source_objects="/o",
                toolchain=[])
        fs = tomllib.loads("fs=" + profile)["fs"]
        self.assertEqual(fs[self.T], "write")
        self.assertEqual(fs[f"{self.T}/[!i]*"], "deny")
        self.assertEqual(fs["/private/var/folders"], "deny")
        none = command.filesystem_profile(
            codex_bin="codex", platform="darwin",
            review_root="/r", workspace_root="/w", source_objects="/o",
            toolchain=[], user_temp=None)
        self.assertNotIn(self.T, none)

    def test_every_generated_entry_is_valid_toml(self):
        profile = command.filesystem_profile(
            codex_bin="codex", platform="darwin",
            review_root="/r", workspace_root="/w",
            source_objects="/o", toolchain=[], user_temp=self.T)
        self.assertIn(f"{self.T}/[!i]*", tomllib.loads("fs=" + profile)["fs"])

    def test_a_linux_profile_gets_no_carve_out(self):
        with mock.patch.object(command, "darwin_user_temp_dir",
                               return_value=self.T):
            profile = command.filesystem_profile(
                codex_bin="codex", platform="linux", review_root="/r",
                workspace_root="/w", source_objects="/o", toolchain=[])
        self.assertNotIn(self.T, profile)

    def test_user_temp_dir_is_macos_only(self):
        with mock.patch.object(command.sys, "platform", "linux"):
            self.assertIsNone(command.darwin_user_temp_dir())

    @unittest.skipUnless(command.sys.platform == "darwin", "macOS only")
    def test_user_temp_dir_is_the_real_per_user_dir(self):
        temp = command.darwin_user_temp_dir()
        self.assertTrue(temp.startswith("/private/var/folders/"), temp)
        self.assertEqual(temp, os.path.realpath(temp))


if __name__ == "__main__":
    unittest.main()
