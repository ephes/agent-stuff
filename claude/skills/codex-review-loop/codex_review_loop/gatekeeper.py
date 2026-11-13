"""Refuse a Codex binary that macOS Gatekeeper would hold at its first launch.

A file a downloader marked with the `com.apple.quarantine` attribute is
assessed by Gatekeeper when it is first executed. For a binary that was never
approved, macOS shows a dialog on the logged-in user's screen and the `exec`
does not return until someone answers it - Codex prints nothing and writes no
session record meanwhile. Observed on 2026-11-13 on a Mac where Homebrew's
`codex` cask had just installed Codex 0.168.0: syspolicyd logged
"Prompt shown ..., waiting for response" at the first review's launch, two
reviews stalled for their full `--stall-timeout` with empty output, and the
next launch worked only after someone confirmed the dialog at the screen
("Allowing code due to user approval"). The npm package sets no quarantine.

The attribute's first field holds hexadecimal flags; `USER_APPROVED` is set
once the file was approved (`0181` before, `01c1` after the confirmation
above). The harness checks only the binary it executes: the package's helpers
(`codex-code-mode-host`) kept an unapproved attribute after that confirmation
and ran without a dialog. An attribute that cannot be read does not block -
the startup timeout still ends a launch that never starts a thread.
"""
import ctypes
import errno
import os
import shlex
import sys

QUARANTINE_ATTR = "com.apple.quarantine"
#: The quarantine flag Gatekeeper sets once a file was approved.
USER_APPROVED = 0x0040
_ENOATTR = getattr(errno, "ENOATTR", 93)


def read_quarantine(path):
    """The `com.apple.quarantine` value of `path` (following symlinks), or
    None when it has none. Raises OSError when it cannot be read."""
    libc = ctypes.CDLL(None, use_errno=True)
    getxattr = libc.getxattr
    getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                         ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    getxattr.restype = ctypes.c_ssize_t
    raw_path, name = os.fsencode(path), QUARANTINE_ATTR.encode()
    for _ in range(3):  # the value can change size between the two calls
        size = getxattr(raw_path, name, None, 0, 0, 0)
        if size < 0:
            err = ctypes.get_errno()
            if err == _ENOATTR:
                return None
            raise OSError(err, os.strerror(err), path)
        buf = ctypes.create_string_buffer(max(size, 1))
        got = getxattr(raw_path, name, buf, size, 0, 0)
        if got >= 0:
            return buf.raw[:got].decode("utf-8", errors="replace")
        err = ctypes.get_errno()
        if err == _ENOATTR:
            return None
        if err != errno.ERANGE:
            raise OSError(err, os.strerror(err), path)
    raise OSError(errno.ERANGE, os.strerror(errno.ERANGE), path)


def is_unapproved(value):
    """Whether a quarantine value marks a file Gatekeeper has not approved.
    Flags that do not parse count as unapproved: the attribute is there, and
    nothing shows the dialog is not."""
    flags = value.split(";", 1)[0].strip()
    try:
        return not int(flags, 16) & USER_APPROVED
    except ValueError:
        return True


def check(path, *, platform=None, reader=read_quarantine):
    """None when `path` may be launched, otherwise why it is refused."""
    if (sys.platform if platform is None else platform) != "darwin":
        return None
    try:
        value = reader(path)
    except OSError:
        return None
    if value is None or not is_unapproved(value):
        return None
    flags = value.split(";", 1)[0].strip()
    return (
        f"the Codex binary {path} is quarantined by macOS and was never "
        f"approved (com.apple.quarantine flags {flags!r}): its first launch "
        "waits, without any output, on a Gatekeeper dialog on the logged-in "
        "user's screen, so Codex was not started. Approve it once at that "
        "screen (run `codex --version` in a Terminal there and confirm the "
        "dialog) or clear the attribute with "
        f"`xattr -d {QUARANTINE_ATTR} {shlex.quote(path)}`, then rerun the "
        "review.")
