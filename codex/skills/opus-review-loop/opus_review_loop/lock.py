"""Atomic, global-per-user lock so only one Claude review runs at a time (concurrent
reviews are what worsen provider API blocking). Uses mkdir for atomicity. Stale
reclaim is reuse-safe: it only removes a lock whose recorded process group is
genuinely gone."""
import errno
import json
import os
import signal
import subprocess

META_NAME = "meta.json"


class LockHeld(Exception):
    """Raised when a live review already holds the lock."""


def write_meta(lock_dir, meta):
    with open(os.path.join(lock_dir, META_NAME), "w") as fh:
        json.dump(meta, fh)


def read_meta(lock_dir):
    try:
        with open(os.path.join(lock_dir, META_NAME)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _group_alive(pgid):
    if not pgid or pgid <= 1:
        return False
    try:
        os.killpg(pgid, 0)  # signal 0 = liveness probe
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned elsewhere; treat as alive (do not reclaim)
    except OSError as e:
        return e.errno != errno.ESRCH


def pid_alive(pid):
    if not pid or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as e:
        return e.errno != errno.ESRCH


def _pgid_is_claude(pgid):
    """Best-effort identity check before killing a recorded process group: confirm
    the group leader's command is `claude` (the leader pid == pgid because Claude
    is spawned with start_new_session). Fail-safe: returns False (do NOT kill) on any
    uncertainty, so a reused PGID never gets an unrelated process group killed."""
    if not pgid or pgid <= 1:
        return False
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pgid)],
                             capture_output=True, text=True, timeout=5,
                             check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    tokens = out.split()
    return any(os.path.basename(token) == "claude" for token in tokens)


def _remove_lock_dir(lock_dir):
    try:
        os.remove(os.path.join(lock_dir, META_NAME))
    except OSError:
        pass
    try:
        os.rmdir(lock_dir)
    except OSError:
        pass


def _reclaim_if_stale(lock_dir):
    """Remove the lock dir iff its holder is provably gone. Reuse-safe and
    fail-closed: never reclaim a lock with no readable metadata."""
    meta = read_meta(lock_dir)
    # Fail closed: a lock dir with no readable metadata may belong to a holder
    # that created the dir microseconds before writing meta. Treat it as held.
    if not meta:
        return False
    # The CLI holds the lock keyed on its own (harness) PID; the runner owns the
    # Claude process. Prefer harness liveness when recorded.
    if "harness_pid" in meta:
        if pid_alive(meta.get("harness_pid")):
            return False
        pgid = meta.get("claude_pgid")  # kill an orphaned group only if it is still claude
        if pgid and pgid > 1 and _pgid_is_claude(pgid):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        _remove_lock_dir(lock_dir)
        return True
    if _group_alive(meta.get("claude_pgid")):
        return False
    pgid = meta.get("claude_pgid")
    if pgid and pgid > 1 and _pgid_is_claude(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    _remove_lock_dir(lock_dir)
    return True


class Lock:
    def __init__(self, lock_dir, meta):
        self.lock_dir = lock_dir
        self.meta = dict(meta)

    def __enter__(self):
        try:
            os.mkdir(self.lock_dir)
        except FileExistsError:
            if not _reclaim_if_stale(self.lock_dir):
                raise LockHeld(f"review lock held: {self.lock_dir}")
            try:
                os.mkdir(self.lock_dir)
            except FileExistsError:
                raise LockHeld(f"review lock held (lost reclaim race): {self.lock_dir}")
        write_meta(self.lock_dir, self.meta)
        return self

    def __exit__(self, *exc):
        try:
            os.remove(os.path.join(self.lock_dir, META_NAME))
        except OSError:
            pass
        try:
            os.rmdir(self.lock_dir)
        except OSError:
            pass
        return False
