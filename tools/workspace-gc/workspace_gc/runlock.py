"""A run lock, so a new run never piles up behind (or next to) a hung one.

`acquire(path)` takes a non-blocking exclusive flock on `path` and writes the
holder's pid and start time into it. The kernel drops the lock when the
holder exits, however it exits, so a crashed or killed run never leaves a
stale lock behind. A second run that finds the lock held gives up at once.
"""

from __future__ import annotations

import fcntl
import os
import time


class Busy(Exception):
    """Another run holds the lock. The message names its pid and start."""


class RunLock:
    def __init__(self, path: str, fd: int):
        self.path = path
        self._fd = fd

    def release(self) -> None:
        if self._fd >= 0:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def acquire(path: str) -> RunLock:
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            holder = os.pread(fd, 200, 0).decode("utf-8", "replace").strip()
        except OSError:
            holder = ""
        os.close(fd)
        raise Busy(f"another workspace-gc run holds {path}"
                   + (f" ({holder})" if holder else ""))
    except BaseException:
        os.close(fd)
        raise
    try:
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid {os.getpid()}, started {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
                  .encode(), 0)
    except OSError:
        pass  # the lock itself is what matters
    return RunLock(path, fd)
