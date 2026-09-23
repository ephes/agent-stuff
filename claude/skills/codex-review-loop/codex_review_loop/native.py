"""Find the native Codex binary behind the `codex` on PATH.

The npm package installs `codex` as a Node launcher that spawns the native
binary and forwards signals to it. Its exit status cannot be trusted: it
installs its own SIGTERM handler, so when it re-raises the signal its child
died of, the handler swallows it and the launcher exits 0 - a reviewer killed
after its turn would read as a clean exit. The harness therefore starts the
native binary itself, whose status is the operating system's own (observed:
-15 for SIGTERM, -9 for SIGKILL).

It also passes the two variables the launcher sets for the binary, so update
checks behave as they do under the launcher. A `codex` that is a script but
whose native binary cannot be found is refused rather than run through the
launcher.
"""
import glob
import os
import shutil

_LAUNCHER_SUFFIX = os.path.join("bin", "codex.js")


class NativeCodexNotFound(Exception):
    pass


def _is_script(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def resolve(which=shutil.which):
    """Return (argv0, env_additions) for the native binary, or raise."""
    found = which("codex")
    if not found:
        raise NativeCodexNotFound("codex is not on PATH")
    real = os.path.realpath(found)
    if not _is_script(real):
        return real, {}
    if not real.endswith(_LAUNCHER_SUFFIX):
        raise NativeCodexNotFound(
            f"codex on PATH is a script this harness does not know: {real}")
    package_root = os.path.dirname(os.path.dirname(real))
    candidates = sorted(glob.glob(os.path.join(
        package_root, "node_modules", "@openai", "codex-*", "vendor", "*",
        "bin", "codex")))
    candidates += sorted(glob.glob(os.path.join(
        package_root, "vendor", "*", "bin", "codex")))
    native = [c for c in candidates if os.access(c, os.X_OK) and not _is_script(c)]
    if len(native) != 1:
        raise NativeCodexNotFound(
            f"expected exactly one native codex binary under {package_root}, "
            f"found {len(native)}")
    return native[0], {"CODEX_MANAGED_PACKAGE_ROOT": package_root,
                       "CODEX_MANAGED_BY_NPM": "1"}
