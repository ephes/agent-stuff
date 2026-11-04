"""Live check that the reviewer's sandbox can run PyPowSyBl.

Skipped unless CODEX_REVIEW_RUN_SANDBOX=1. It spends no model run: the
installed Codex runs plain commands under the production permission profile
(`codex sandbox`), in a copy built by the production copy builder, with HOME,
TMPDIR and PATH set as the reviewer's shell sees them. It needs macOS, `uv`
and Python 3.14 in a toolchain prefix, and the network: like a reviewer, it
installs `pypowsybl` into the copy from inside the sandbox.

PyPowSyBl is a GraalVM native image that puts its `itools_common_*`
directories in the macOS per-user temporary directory whatever TMPDIR and
HOME say; that directory is denied to the reviewer except for the `itools_`
carve-out (`command.powsybl_temp_entries`). Run this after any change to the
permission profile or the Codex version.
"""
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest

from tests.helpers import git
from codex_review_loop import command
from codex_review_loop._shared import workspace

RUN = os.environ.get("CODEX_REVIEW_RUN_SANDBOX") == "1"
PYPOWSYBL = "pypowsybl==1.16.1"
XNODE = "XBENL111"

# Two areas joined at one X-node; merged, they share exactly one tie line.
PROBE = """\
import sys, pypowsybl as pp
a, b = pp.network.load(sys.argv[1]), pp.network.load(sys.argv[2])
a.merge([b])
print("TIE_LINES", sorted(a.get_tie_lines().index))
"""


def _node(code, name, typ, volt, load, gen, limits=""):
    return (f"{code:<8} {name:<12} 0 {typ} {volt:>6} {load:>7} {'0':>7} "
            f"{gen:>7} {'0':>7}{limits}")


def ucte_area(country, generation, load):
    """A two-bus UCTE area whose second bus ends at the shared X-node."""
    limits = " -9000.0 9000.00 -9000.0 9000.00"
    n1, n2 = f"{country[0]}{country}1AA11", f"{country[0]}{country}2AA11"
    return "\n".join([
        "##C 2007.05.01", "synthetic", "##N", f"##Z{country}",
        _node(n1, n1[:7], 3, "400.00", "0", f"-{generation}", limits),
        _node(n2, n2[:7], 2, "400.00", load, "0", limits),
        "##ZXX", _node(XNODE, "XBENL1", 0, "", "0", "0"),
        "##L",
        f"{n1:<8} {n2:<8} 1 0 0.0000 10.000 0.000000   5000",
        f"{n2:<8} {XNODE:<8} 1 0 0.0000 5.0000 0.000000   5000", ""])


@unittest.skipUnless(RUN, "set CODEX_REVIEW_RUN_SANDBOX=1 to run the sandbox")
class TestSandboxRunsPowsybl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user_temp = command.darwin_user_temp_dir()
        if not cls.user_temp:
            raise unittest.SkipTest("needs the macOS per-user temporary dir")
        cls.codex = shutil.which("codex")
        if not cls.codex:
            raise unittest.SkipTest("needs codex on PATH")
        cls.toolchain = [p for p in command.TOOLCHAIN_READ_PATHS
                         if os.path.isdir(p)]
        cls.path = ":".join([os.path.join(p, "bin") for p in cls.toolchain]
                            + ["/usr/bin", "/bin"])
        # Outside the macOS temporary directory: a run there gets no
        # carve-out (see test_a_run_inside_the_temp_dir_gets_no_carve_out).
        cls.base = os.path.realpath(
            tempfile.mkdtemp(prefix="codex-sandbox-", dir="/private/tmp"))
        repo = os.path.join(cls.base, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")
        for name, text in (("be.uct", ucte_area("BE", "500.0", "100.0")),
                           ("nl.uct", ucte_area("NL", "100.0", "500.0")),
                           ("probe.py", PROBE)):
            with open(os.path.join(repo, name), "w") as fh:
                fh.write(text)
        git(repo, "add", ".")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
        cls.review_root = os.path.join(cls.base, "review-root")
        os.makedirs(cls.review_root)
        cls.copy = workspace.create_copy(repo, os.path.join(cls.base, "workspace"))
        install = cls.sandboxed(
            cls.profile(),
            "uv venv -q -p 3.14 --python-preference only-system .venv && "
            f"uv pip install -q -p .venv/bin/python {PYPOWSYBL}")
        if install.returncode != 0:
            cls.tearDownClass()
            raise AssertionError("installing pypowsybl in the sandbox failed:\n"
                                 + install.stdout + install.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.copy.remove()
        shutil.rmtree(cls.base, ignore_errors=True)

    @classmethod
    def profile(cls, user_temp=None):
        return command.filesystem_profile(
            codex_bin=cls.codex,
            review_root=cls.review_root, workspace_root=cls.copy.root,
            source_objects=cls.copy.source_objects, toolchain=cls.toolchain,
            user_temp=user_temp or cls.user_temp)

    @classmethod
    def sandboxed(cls, profile, script):
        name = command.PROFILE_NAME
        cmd = [cls.codex, "sandbox",
               "-c", f"default_permissions={command.toml_string(name)}",
               "-c", f"permissions.{name}.filesystem={profile}",
               "-c", f"permissions.{name}.network.enabled=true",
               "--", "/usr/bin/env", "-i",
               f"HOME={os.path.realpath(cls.copy.home)}",
               f"TMPDIR={os.path.realpath(cls.copy.tmp)}",
               f"PATH={cls.path}", "/bin/sh", "-c", script]
        return subprocess.run(cmd, cwd=cls.copy.path, capture_output=True,
                              text=True, timeout=600)

    def probe(self, profile):
        return self.sandboxed(profile, ".venv/bin/python probe.py be.uct nl.uct")

    def test_reviewer_loads_and_merges_ucte_networks(self):
        run = self.probe(self.profile())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"TIE_LINES ['BBE2AA11 {XNODE} 1 + NNL2AA11 {XNODE} 1']",
                      run.stdout)

    def test_without_the_carve_out_pypowsybl_cannot_load(self):
        # The premise: TMPDIR and HOME in the copy do not move PowSyBl's
        # scratch directories, so the plain profile refuses them.
        bare = command.filesystem_profile(
            codex_bin=self.codex,
            review_root=self.review_root, workspace_root=self.copy.root,
            source_objects=self.copy.source_objects, toolchain=self.toolchain,
            user_temp=None)
        run = self.probe(bare)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("itools_common_", run.stdout + run.stderr)
        self.assertIn("Operation not permitted", run.stdout + run.stderr)

    def test_a_run_inside_the_temp_dir_gets_no_carve_out(self):
        # As with `--run-dir "$(mktemp -d)/..."`: the profile must still
        # compile, and the temp dir stays denied as a whole.
        inside = os.path.join(self.user_temp, f"codex-sandbox-{secrets.token_hex(4)}")
        profile = command.filesystem_profile(
            codex_bin=self.codex,
            review_root=os.path.join(inside, "review-root"),
            workspace_root=os.path.join(inside, "workspace"),
            source_objects=self.copy.source_objects, toolchain=self.toolchain,
            user_temp=self.user_temp)
        self.assertNotIn("[!i]*", profile)
        own = os.path.join(self.user_temp, f"itools_probe_{secrets.token_hex(4)}")
        run = self.sandboxed(profile, f"echo COMPILED; mkdir '{own}'")
        self.assertIn("COMPILED", run.stdout, run.stderr)
        self.assertIn("Operation not permitted", run.stderr)
        self.assertFalse(os.path.exists(own))

    def test_other_files_in_the_user_temp_dir_stay_denied(self):
        marker = f"denied-{secrets.token_hex(8)}"
        plain = os.path.join(self.user_temp, f"codex-sandbox-{marker}.txt")
        nested_dir = os.path.join(self.user_temp, f"codex-sandbox-{marker}")
        near = os.path.join(self.user_temp, f"itoolsX-{marker}")
        # Beside the copy, inside the run's base directory.
        sibling = os.path.join(self.base, f"sibling-{marker}.txt")
        os.makedirs(nested_dir)
        nested = os.path.join(nested_dir, "inner.txt")
        try:
            for path in (plain, nested, near, sibling):
                with open(path, "w") as fh:
                    fh.write(marker + "\n")
            new = os.path.join(self.user_temp, f"codex-sandbox-new-{marker}")
            own = os.path.join(self.user_temp, f"itools_probe_{marker}")
            run = self.sandboxed(self.profile(), "; ".join([
                f"cat '{plain}'", f"cat '{nested}'", f"cat '{near}'",
                f"cat '{sibling}'",
                f"ls '{nested_dir}'",
                f"cat '{self.user_temp.lower()}/{os.path.basename(plain)}'",
                f"touch '{new}'",
                f"mkdir '{own}' && echo x > '{own}/f' && echo OWN_OK",
                f"ln '{plain}' '{own}/hardlink'",
                f"mv '{nested_dir}' '{own}-moved'",
                f"rm -r '{own}'"]))
            self.assertNotIn(marker + "\n", run.stdout)
            self.assertFalse(os.path.exists(new))
            self.assertTrue(os.path.exists(nested))
            self.assertIn("OWN_OK", run.stdout)
            self.assertEqual(run.stderr.count("Operation not permitted"), 9,
                             run.stderr)
        finally:
            for path in (plain, nested, near, sibling):
                if os.path.exists(path):
                    os.unlink(path)
            shutil.rmtree(nested_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
