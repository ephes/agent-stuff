"""Pi's review slot pool is the shared pool from `claude-review-loop`.

The pool is reviewer-agnostic: bounded slots, a guard file per slot so a
displaced or externally deleted directory cannot hand the same slot to a second
live holder, owner tokens so a reclaimed harness cannot overwrite or delete its
replacement's slot, atomic metadata, and a unique tombstone for a proven-stale
slot. This module used to be a smaller, older implementation with none of that,
which mattered more here than on the sibling path: a double-held Pi slot means
two concurrent reviews egressing a diff to an external provider.

Only the reviewer identity differs, so that is all this module supplies.
"""
import os
import subprocess

from ._shared import lock as _shared

LockHeld = _shared.LockHeld
META_NAME = _shared.META_NAME
write_meta = _shared.write_meta
read_meta = _shared.read_meta
pid_alive = _shared.pid_alive

DEFAULT_MAX_CONCURRENT = 3


def _pgid_is_pi(pgid):
    """Best-effort identity check before killing a recorded process group.

    Confirm the group leader's command is `pi` - the leader pid equals the pgid
    because Pi is spawned with start_new_session=True. Fail-safe: returns False
    (do NOT kill) on any uncertainty, so a reused PGID never gets an unrelated
    process group killed.
    """
    if not pgid or pgid <= 1:
        return False
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pgid)],
                             capture_output=True, text=True, timeout=5,
                             check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    tokens = out.split()
    return bool(tokens) and os.path.basename(tokens[0]) == "pi"


PI_PROFILE = _shared.ReviewerProfile("pi_pgid", _pgid_is_pi)


class Lock(_shared.Lock):
    def __init__(self, lock_dir, meta, profile=PI_PROFILE):
        super().__init__(lock_dir, meta, profile)


class LockPool(_shared.LockPool):
    """Acquire one slot from a bounded per-user review pool.

    A single global lock serialized every repository behind one Pi call. The
    pool keeps a hard cap for provider protection while allowing unrelated
    agents to review in parallel.
    """

    def __init__(self, pool_dir, meta, max_concurrent=DEFAULT_MAX_CONCURRENT,
                 selection_timeout=5.0, profile=PI_PROFILE):
        super().__init__(pool_dir, meta, max_concurrent=max_concurrent,
                         selection_timeout=selection_timeout, profile=profile)


__all__ = [
    "LockHeld", "META_NAME", "write_meta", "read_meta", "pid_alive",
    "Lock", "LockPool", "PI_PROFILE", "DEFAULT_MAX_CONCURRENT",
]
