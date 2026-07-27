"""Atomic, bounded per-user locks for concurrent Claude reviews.

Each review acquires one slot from a shared pool. A short-lived pool guard
serializes slot selection, while a per-slot advisory lock is held for the
review's full lifecycle. Independent occupied slots therefore run concurrently.
Proven-stale directories are atomically renamed to a unique tombstone before
cleanup, and owner tokens protect metadata updates and release from deleting a
replacement owner's lock.
"""
import errno
import fcntl
import json
import os
import re
import signal
import subprocess
import time
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
            raise RuntimeError("cannot update an unowned review lock")
        current = read_meta(self.lock_dir)
        if current.get("owner_token") != self.owner_token:
            raise RuntimeError("review lock ownership changed before metadata update")
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


class LockPool:
    """Acquire one lifecycle slot without serializing unrelated reviews."""

    def __init__(
        self,
        pool_dir,
        meta,
        max_concurrent=3,
        selection_timeout=5.0,
    ):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if selection_timeout < 0:
            raise ValueError("selection_timeout must be >= 0")
        self.pool_dir = pool_dir
        self.selection_guard_path = os.path.join(pool_dir, ".pool.guard")
        self.meta = dict(meta)
        self.max_concurrent = max_concurrent
        self.selection_timeout = selection_timeout
        self._lock = None
        self.lock_dir = None
        self.slot = None

    def _active_slots(self):
        active = []
        highest_slot = -1
        with os.scandir(self.pool_dir) as entries:
            for entry in entries:
                match = re.fullmatch(r"slot-(\d+)", entry.name)
                if not match or not entry.is_dir(follow_symlinks=False):
                    continue
                slot = int(match.group(1))
                highest_slot = max(highest_slot, slot)
                if _reclaim_if_stale(entry.path):
                    continue
                if not os.path.isdir(entry.path):
                    continue
                meta = read_meta(entry.path)
                try:
                    recorded_limit = int(meta["max_concurrent"])
                    if recorded_limit < 1:
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    # Fail closed for old, malformed, or mid-write metadata.
                    recorded_limit = 1
                active.append((slot, recorded_limit))
        return active, highest_slot

    def _acquire_selection_guard(self, selection_fd):
        deadline = time.monotonic() + self.selection_timeout
        while True:
            try:
                fcntl.flock(selection_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockHeld(
                        f"review slot selection busy: {self.pool_dir}"
                    ) from exc
                time.sleep(min(0.05, remaining))

    def __enter__(self):
        os.makedirs(self.pool_dir, exist_ok=True)
        selection_fd = os.open(
            self.selection_guard_path, os.O_CREAT | os.O_RDWR, 0o600
        )
        selection_acquired = False
        try:
            self._acquire_selection_guard(selection_fd)
            selection_acquired = True
            active, highest_slot = self._active_slots()
            effective_limit = min(
                [self.max_concurrent, *(limit for _, limit in active)]
            )
            if len(active) >= effective_limit:
                raise LockHeld(
                    f"{len(active)} review slot(s) held, "
                    f"active limit {effective_limit}: {self.pool_dir}"
                )

            occupied = {slot for slot, _ in active}
            search_span = max(self.max_concurrent, highest_slot + 1)
            for slot in range(search_span):
                if slot in occupied:
                    continue
                slot_dir = os.path.join(self.pool_dir, f"slot-{slot}")
                slot_meta = {
                    **self.meta,
                    "lock_slot": slot,
                    "max_concurrent": self.max_concurrent,
                }
                candidate = Lock(slot_dir, slot_meta)
                try:
                    candidate.__enter__()
                except LockHeld:
                    # A live per-slot guard can outlast a displaced directory.
                    # Try another slot without misclassifying it as pool-wide
                    # exhaustion.
                    continue
                self._lock = candidate
                self.lock_dir = slot_dir
                self.slot = slot
                return self
            raise LockHeld(
                f"no selectable review slot among {search_span} candidates "
                f"(active limit {effective_limit}): {self.pool_dir}"
            )
        finally:
            try:
                if selection_acquired:
                    fcntl.flock(selection_fd, fcntl.LOCK_UN)
            finally:
                os.close(selection_fd)

    def update_meta(self, updates):
        if self._lock is None:
            raise RuntimeError("cannot update an unowned review slot")
        self._lock.update_meta(updates)

    def __exit__(self, *exc):
        if self._lock is None:
            return False
        try:
            return self._lock.__exit__(*exc)
        finally:
            self._lock = None
            self.lock_dir = None
            self.slot = None
