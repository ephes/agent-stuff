"""Atomic, global-per-user lock so only one Pi review runs at a time (concurrent
reviews are what worsen provider API blocking). Uses mkdir for atomicity. Stale
reclaim is reuse-safe: it only removes a lock whose recorded process group is
genuinely gone."""
import errno
import json
import os
import signal

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


def _reclaim_if_stale(lock_dir):
    """Remove the lock dir iff its recorded process group is dead. Returns True
    if it reclaimed (or the dir vanished)."""
    meta = read_meta(lock_dir)
    # Fail closed: a lock dir with no readable metadata may belong to a holder
    # that created the dir microseconds before writing meta. Treat it as held,
    # never reclaim it — reclaiming could double-hold the lock.
    if not meta:
        return False
    if _group_alive(meta.get("pi_pgid")):
        return False
    # Group is gone: best-effort kill (tolerate ESRCH) then remove the dir.
    pgid = meta.get("pi_pgid")
    if pgid and pgid > 1:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        os.remove(os.path.join(lock_dir, META_NAME))
    except OSError:
        pass
    try:
        os.rmdir(lock_dir)
    except OSError:
        pass
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
