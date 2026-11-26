"""A run lock, so a new run never piles up behind (or next to) a hung one.

`acquire(path)` takes a non-blocking exclusive flock on `path` and writes the
holder's pid and the time it took the lock into it. The kernel drops the lock
when the holder exits, however it exits, so a crashed or killed run never
leaves a stale lock behind. A second run that finds the lock held gives up at once,
or, with `wait` seconds, retries every `poll` seconds until the lock is free
or the wait is over (`remove` and `report` wait by default, so a runner's or
clerk's removal is not skipped just because the daily run is busy, and the
daily run is not skipped because such a removal is under way).
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import suppress


class Busy(Exception):
    """Another run holds the lock. The message names its pid and start."""


class RunLock:
    def __init__(self, path: str, fd: int):
        self.path = path
        self._fd = fd

    def release(self) -> None:
        fd = self._fd
        if fd < 0:
            return
        # Even a failed close can free the descriptor number for reuse.
        self._fd = -1
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BaseException:
            with suppress(OSError):
                os.close(fd)
            raise
        else:
            os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def acquire(path: str, wait: float = 0.0, poll: float = 5.0) -> RunLock:
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    deadline = time.monotonic() + max(wait, 0.0)
    while True:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    holder = os.pread(fd, 200, 0).decode("utf-8", "replace").strip()
                except OSError:
                    holder = ""
            else:
                try:
                    os.ftruncate(fd, 0)
                    stamp = f"pid {os.getpid()}, locked since {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
                    os.pwrite(fd, stamp.encode(), 0)
                except OSError:
                    pass  # the lock itself is what matters
                return RunLock(path, fd)
        except BaseException:
            with suppress(OSError):
                os.close(fd)
            raise
        os.close(fd)
        left = deadline - time.monotonic()
        if left <= 0:
            raise Busy(f"another workspace-gc run holds {path}"
                       + (f" ({holder})" if holder else "")
                       + (f"; waited {wait:g}s" if wait > 0 else ""))
        time.sleep(min(poll, left))
