"""Codex's review slot pool is the shared pool from `claude-review-loop`.

Only the reviewer identity differs. The default is one slot: concurrent Codex
reviews on one account slowed each other badly enough to hit their deadlines.
"""
import os
import subprocess

from ._shared import lock as _shared

LockHeld = _shared.LockHeld
META_NAME = _shared.META_NAME
write_meta = _shared.write_meta
read_meta = _shared.read_meta
pid_alive = _shared.pid_alive

DEFAULT_MAX_CONCURRENT = 1


def _pgid_is_codex(pgid):
    """Best-effort identity check before killing a recorded process group.

    The group leader is the `codex` launcher, which npm installs as a Node
    script, so the leader's argv is `node .../codex ...` or the native binary
    itself. Fail-safe: returns False (do NOT kill) on any uncertainty.
    """
    if not pgid or pgid <= 1:
        return False
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pgid)],
                             capture_output=True, text=True, timeout=5,
                             check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    tokens = out.split()[:2]
    return any(os.path.basename(t) in ("codex", "codex.js") for t in tokens)


CODEX_PROFILE = _shared.ReviewerProfile("codex_pgid", _pgid_is_codex)


class Lock(_shared.Lock):
    def __init__(self, lock_dir, meta, profile=CODEX_PROFILE):
        super().__init__(lock_dir, meta, profile)


class LockPool(_shared.LockPool):
    def __init__(self, pool_dir, meta, max_concurrent=DEFAULT_MAX_CONCURRENT,
                 selection_timeout=5.0, profile=CODEX_PROFILE):
        super().__init__(pool_dir, meta, max_concurrent=max_concurrent,
                         selection_timeout=selection_timeout, profile=profile)


__all__ = [
    "LockHeld", "META_NAME", "write_meta", "read_meta", "pid_alive",
    "Lock", "LockPool", "CODEX_PROFILE", "DEFAULT_MAX_CONCURRENT",
]
