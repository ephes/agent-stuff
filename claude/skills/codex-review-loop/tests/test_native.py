import os
import stat
import tempfile
import unittest

from codex_review_loop import native


def write(path, data, mode=0o755):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.pkg = os.path.join(self.root, "lib", "node_modules", "@openai", "codex")
        self.launcher = os.path.join(self.pkg, "bin", "codex.js")
        write(self.launcher, b"#!/usr/bin/env node\n")
        self.link = os.path.join(self.root, "bin", "codex")
        os.makedirs(os.path.dirname(self.link))
        os.symlink(self.launcher, self.link)

    def tearDown(self):
        self.tmp.cleanup()

    def which(self, name):
        return self.link

    def test_the_npm_launcher_resolves_to_its_native_binary(self):
        binary = os.path.join(self.pkg, "node_modules", "@openai", "codex-darwin-arm64",
                              "vendor", "aarch64-apple-darwin", "bin", "codex")
        write(binary, b"\xcf\xfa\xed\xfe native")
        path, env = native.resolve(which=self.which)
        self.assertEqual(path, binary)
        self.assertEqual(env, {"CODEX_MANAGED_PACKAGE_ROOT": self.pkg,
                               "CODEX_MANAGED_BY_NPM": "1"})

    def test_a_launcher_without_a_native_binary_is_refused(self):
        with self.assertRaises(native.NativeCodexNotFound):
            native.resolve(which=self.which)

    def test_two_native_binaries_are_ambiguous_and_refused(self):
        for platform in ("codex-darwin-arm64", "codex-darwin-x64"):
            write(os.path.join(self.pkg, "node_modules", "@openai", platform, "vendor",
                               "t", "bin", "codex"), b"\xcf\xfa\xed\xfe")
        with self.assertRaises(native.NativeCodexNotFound):
            native.resolve(which=self.which)

    def test_an_unknown_script_is_refused(self):
        other = os.path.join(self.root, "wrapper.sh")
        write(other, b"#!/bin/sh\nexec codex \"$@\"\n")
        with self.assertRaises(native.NativeCodexNotFound):
            native.resolve(which=lambda name: other)

    def test_a_native_codex_on_path_is_used_as_is(self):
        binary = os.path.join(self.root, "codex-native")
        write(binary, b"\xcf\xfa\xed\xfe")
        self.assertEqual(native.resolve(which=lambda name: binary), (binary, {}))

    def test_no_codex_is_refused(self):
        with self.assertRaises(native.NativeCodexNotFound):
            native.resolve(which=lambda name: None)


if __name__ == "__main__":
    unittest.main()
