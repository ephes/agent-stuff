"""Atomic, global-per-user lock so only one Claude review runs at a time.

An OS advisory file lock serializes the full lifecycle; mkdir provides the
visible ownership record. Proven-stale directories are atomically renamed to a
unique tombstone before cleanup, and owner tokens protect metadata updates and
release from deleting a replacement owner's lock.
"""
import errno
import fcntl
import json
import os
import signal
import subprocess
import uuid

META_NAME = "meta.json"


class LockHeld(Exception):
    """Raised when a live review already holds the lock."""


def write_meta(lock_dir, meta):
    path = os.path.join(lock_dir, META_NAME)
    temp_path = os.path.join(lock_dir, f".{META_NAME}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        os.replace(temp_path, path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def read_meta(lock_dir):
    try:
        with open(os.path.join(lock_dir, META_NAME), encoding="utf-8") as fh:
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
    """Best-effort identity check before killing a recorded process group.

    Confirm the group leader is either Claude itself or the fish `claude-yolo`
    wrapper used to launch Claude. Fail-safe: returns False (do NOT kill) on any
    uncertainty, so a reused PGID never gets an unrelated process group killed.
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
    if any(os.path.basename(token) == "claude" for token in tokens):
        return True
    return (
        any(os.path.basename(token) == "fish" for token in tokens)
        and "claude-yolo" in out
    )


def _remove_lock_dir(lock_dir):
    try:
        entries = list(os.scandir(lock_dir))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file(follow_symlinks=False) or entry.is_symlink():
                os.remove(entry.path)
        except OSError:
            pass
    try:
        os.rmdir(lock_dir)
    except OSError:
        pass


def _retire_stale_lock(lock_dir, meta):
    """Atomically take ownership of a proven-stale directory before cleanup."""
    tombstone = f"{lock_dir}.stale.{uuid.uuid4().hex}"
    try:
        os.rename(lock_dir, tombstone)
    except FileNotFoundError:
        return True  # another contender retired it; caller may retry mkdir
    except OSError:
        return False

    pgid = meta.get("claude_pgid")
    if pgid and pgid > 1 and _pgid_is_claude(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    _remove_lock_dir(tombstone)
    return True


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
        return _retire_stale_lock(lock_dir, meta)
    if _group_alive(meta.get("claude_pgid")):
        return False
    return _retire_stale_lock(lock_dir, meta)


class Lock:
    def __init__(self, lock_dir, meta):
        self.lock_dir = lock_dir
        self.guard_path = lock_dir + ".guard"
        self.guard_fd = None
        self.meta = dict(meta)
        self.owner_token = uuid.uuid4().hex
        self.meta["owner_token"] = self.owner_token
        self.acquired = False

    def _acquire_guard(self):
        fd = os.open(self.guard_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(fd)
            raise LockHeld(f"review lock held: {self.lock_dir}")
        self.guard_fd = fd

    def _release_guard(self):
        if self.guard_fd is None:
            return
        try:
            fcntl.flock(self.guard_fd, fcntl.LOCK_UN)
        finally:
            os.close(self.guard_fd)
            self.guard_fd = None

    def __enter__(self):
        self._acquire_guard()
        owned_dir = False
        try:
            for _ in range(3):
                try:
                    os.mkdir(self.lock_dir)
                    owned_dir = True
                    break
                except FileExistsError:
                    if not _reclaim_if_stale(self.lock_dir):
                        raise LockHeld(f"review lock held: {self.lock_dir}")
            else:
                raise LockHeld(f"review lock held (reclaim contention): {self.lock_dir}")
            write_meta(self.lock_dir, self.meta)
        except BaseException:
            current = read_meta(self.lock_dir)
            # Empty metadata means the write failed after our guarded mkdir.
            if owned_dir and (
                not current or current.get("owner_token") == self.owner_token
            ):
                _remove_lock_dir(self.lock_dir)
            self._release_guard()
            raise
        self.acquired = True
        return self

    def update_meta(self, updates):
        if not self.acquired:
            raise LockHeld("cannot update an unowned review lock")
        current = read_meta(self.lock_dir)
        if current.get("owner_token") != self.owner_token:
            raise LockHeld("review lock ownership changed before metadata update")
        self.meta.update(updates)
        self.meta["owner_token"] = self.owner_token
        write_meta(self.lock_dir, self.meta)

    def __exit__(self, *exc):
        if not self.acquired:
            return False
        current = read_meta(self.lock_dir)
        try:
            if current.get("owner_token") == self.owner_token:
                _remove_lock_dir(self.lock_dir)
        finally:
            self.acquired = False
            self._release_guard()
        return False
