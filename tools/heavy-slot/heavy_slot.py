"""heavy-slot: run a heavy command (full test suite, cold build) only while one of N shared slots is free.

Every worker on a machine (Codex jobs, merge clerks, Claude workers) wraps its heavy steps in
``heavy-slot -- <command>``. The slots are ``slot-<k>.lock`` files in one shared directory. heavy-slot
takes a free one with ``flock`` and then *becomes* the command (``exec``), passing the locked file
descriptor on. The command therefore has heavy-slot's pid, gets every signal directly and exits with
its own status, and the slot stays taken as long as any process holding that descriptor lives (the
command and the children it starts without closing inherited descriptors). The kernel releases the
lock when the last of them exits in any way, so a slot can never stay stale. A command that is already
inside a slot can run at once when it requests the same pool and still holds the slot descriptor.

Python 3 stdlib only (3.9+). See README.md.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import math
import os
import resource
import signal
import stat
import sys
import time
from pathlib import Path

DEFAULT_DIR = "~/.cache/heavy-slot"
DEFAULT_SLOTS = 3
MAX_SLOTS = 64
DEFAULT_MAX_WAIT = 7200.0
POLL = 2.0
EX_TEMPFAIL = 75  # no slot within --max-wait
EX_USAGE = 2
EX_NOEXEC = 127
LOCK_FD_MIN = 200  # the inherited lock lives on a high descriptor, out of the way of `exec 3>&1` & co.
UNGUARDED = "none"


def slot_count(text: str) -> int:
    value = int(text)
    if not 1 <= value <= MAX_SLOTS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_SLOTS}")
    return value


def nonnegative_finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be a finite, nonnegative number")
    return value


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="heavy-slot",
        description="Run COMMAND once one of N machine-wide slots is free (cap for parallel heavy runs).",
    )
    p.add_argument("--slots", type=slot_count, default=None,
                   help=f"number of slots, 1 to {MAX_SLOTS} (HEAVY_SLOTS, default {DEFAULT_SLOTS})")
    p.add_argument("--dir", default=None, help=f"slot directory (HEAVY_SLOT_DIR, default {DEFAULT_DIR})")
    p.add_argument("--max-wait", type=nonnegative_finite_float, default=None,
                   help=f"seconds to wait for a slot, then exit {EX_TEMPFAIL}; 0 waits forever "
                        f"(HEAVY_SLOT_MAX_WAIT, default {DEFAULT_MAX_WAIT:.0f})")
    p.add_argument("--label", default="", help="shown to waiting callers (default: executable basename)")
    p.add_argument("--status", action="store_true", help="list the slots and their holders, then exit")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- COMMAND [ARGS...]")
    return p


def setting(value, env: str, default, kind):
    if value is not None:
        return value
    raw = os.environ.get(env, "")
    if raw == "":
        return default
    try:
        return kind(raw)
    except (ValueError, argparse.ArgumentTypeError):
        raise SystemExit(f"heavy-slot: {env}={raw!r} is not valid") from None


def slot_paths(directory: Path, slots: int) -> list[Path]:
    return [directory / f"slot-{k}.lock" for k in range(slots)]


def open_slot(path: Path, flags: int) -> int:
    # A FIFO must not block open before its type can be checked.
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError(errno.EINVAL, "slot requires a regular file with one link", str(path))
    except BaseException:
        os.close(fd)
        raise
    return fd


def try_acquire(paths: list[Path]) -> tuple[int, Path] | None:
    """An open fd holding the first free slot's lock, or None when all are taken."""

    for path in paths:
        fd = open_slot(path, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        except BaseException:
            os.close(fd)
            raise
        return fd, path
    return None


def slot_state(path: Path, *, read_holder: bool = False) -> tuple[bool, str]:
    try:
        fd = open_slot(path, os.O_RDONLY)
    except FileNotFoundError:
        return False, ""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if read_holder:
            try:
                with open(fd, encoding="utf-8", errors="replace", closefd=False) as stream:
                    return True, single_line(stream.read(200))
            except OSError:
                pass  # The lock probe succeeded even if the holder line is unreadable.
        return True, ""
    finally:
        os.close(fd)
    return False, ""


def is_held(path: Path) -> bool:
    return slot_state(path)[0]


def single_line(text: str) -> str:
    return "".join(char if char.isprintable() else " " for char in text).strip()


def holder(path: Path) -> str:
    """The holder line of a held slot (a free slot's file may still name its last holder)."""

    try:
        return slot_state(path, read_holder=True)[1]
    except OSError:
        return ""


def status(paths: list[Path]) -> int:
    for path in paths:
        try:
            held, line = slot_state(path, read_holder=True)
        except OSError:
            print(f"{path.name}\tunavailable")
        else:
            print(f"{path.name}\t" + (f"held\t{line}" if held else "free"))
    return 0


def inherited_slot_fd(path: Path) -> int | None:
    try:
        fd = int(os.environ.get("HEAVY_SLOT_HELD_FD", ""))
        if fd <= 2:
            return None
        inherited = os.fstat(fd)
        current = path.lstat()
        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or not os.path.samestat(inherited, current):
            return None
        # A separately opened descriptor to the same inode does not share an existing lock.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError, OverflowError):
        return None
    return fd


def become(command: list[str], held: str, pool: str | None = None, fd: int | None = None) -> int:
    """Replace this process with ``command`` (returns only when it cannot be started)."""

    os.environ["HEAVY_SLOT_HELD"] = held
    if pool is None:
        os.environ.pop("HEAVY_SLOT_HELD_DIR", None)
        os.environ.pop("HEAVY_SLOT_HELD_FD", None)
    else:
        os.environ["HEAVY_SLOT_HELD_DIR"] = pool
        os.environ["HEAVY_SLOT_HELD_FD"] = str(fd)
    for stream in (sys.stdout, sys.stderr):  # None when the caller closed that descriptor
        if stream is not None:
            try:
                stream.flush()
            except (OSError, ValueError):
                pass
    # Python ignores SIGPIPE and SIGXFSZ, and exec keeps ignored dispositions: restore the defaults
    # the command would have had without heavy-slot.
    restore = {}
    for name in ("SIGPIPE", "SIGXFSZ"):
        if hasattr(signal, name):
            restore[name] = signal.signal(getattr(signal, name), signal.SIG_DFL)
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        for name, handler in restore.items():  # back to Python's own, so the diagnostic cannot die of SIGPIPE
            signal.signal(getattr(signal, name), handler)
        warn(f"heavy-slot: cannot run {command[0]}: {exc}")
    return EX_NOEXEC


def warn(text: str) -> None:
    """One line straight to fd 2: no Python buffer is left that could fail at exit and change the code."""

    try:
        os.write(2, (text + "\n").encode("utf-8", "backslashreplace"))
    except OSError:
        pass


def park(fd: int) -> int | None:
    """A duplicate of ``fd`` (sharing its lock) on fd >= LOCK_FD_MIN, else on the highest free fd > 2."""

    soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    top = LOCK_FD_MIN if soft == resource.RLIM_INFINITY else min(LOCK_FD_MIN, soft - 1)
    for start in [LOCK_FD_MIN] + list(range(top, 2, -1)):
        try:
            return fcntl.fcntl(fd, fcntl.F_DUPFD, start)
        except OSError:
            continue
    return None


def unguarded(command: list[str], reason: str) -> int:
    """The slot directory is unusable (e.g. not writable in a sandbox): run without a slot.

    The cap is a load brake, not a correctness guard; a worker that could not run its tests at all
    would be worse. The warning names the cause so the runner configuration can be fixed."""

    warn(f"heavy-slot: WARNING {reason}; running WITHOUT a slot")
    return become(command, UNGUARDED)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    slots = setting(args.slots, "HEAVY_SLOTS", DEFAULT_SLOTS, slot_count)
    max_wait = setting(args.max_wait, "HEAVY_SLOT_MAX_WAIT", DEFAULT_MAX_WAIT, nonnegative_finite_float)
    directory = Path(setting(args.dir, "HEAVY_SLOT_DIR", DEFAULT_DIR, str)).expanduser()
    if not args.status and not command:
        warn("heavy-slot: no command (usage: heavy-slot [options] -- COMMAND [ARGS...])")
        return EX_USAGE
    paths = slot_paths(directory, slots)
    if args.status:
        return status(paths)
    pool = os.path.realpath(directory)
    held = os.environ.get("HEAVY_SLOT_HELD")
    if held and os.environ.get("HEAVY_SLOT_HELD_DIR") == pool:
        path = directory / held
        if path in paths:
            fd = inherited_slot_fd(path)
            if fd is not None:
                return become(command, path.name, pool, fd)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return unguarded(command, f"cannot create {directory}: {exc}")

    label = single_line((args.label or os.path.basename(command[0]))[:120])
    # Use the full budget if dividing a tiny positive wait rounds down to zero.
    interval = min(POLL, max_wait / 4 or max_wait) if max_wait else POLL
    started = time.monotonic()
    announced = False
    while True:
        try:
            got = try_acquire(paths)
        except OSError as exc:
            waited = time.monotonic() - started
            if max_wait and waited > max_wait:
                warn(f"heavy-slot: no slot after {waited:.0f} s; not run: {label}")
                return EX_TEMPFAIL
            return unguarded(command, f"cannot use {directory}: {exc}")
        waited = time.monotonic() - started
        if got and max_wait and waited > max_wait:
            os.close(got[0])  # acquired, but only after the deadline: too late
            got = None
        if got:
            break
        if max_wait and waited >= max_wait:
            warn(f"heavy-slot: no free slot after {waited:.0f} s (all {slots} held); not run: {label}")
            return EX_TEMPFAIL
        if not announced:
            held = "; ".join(h for h in (holder(p) for p in paths) if h)
            warn(f"heavy-slot: all {slots} slots busy, waiting (holders: {held or 'unknown'})")
            announced = True
        if max_wait:
            remaining = max_wait - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(min(interval, remaining))
        else:
            time.sleep(interval)
    fd, path = got
    # First move the lock off a standard descriptor it may have taken (a closed stdin/stdout/stderr),
    # before anything is written, so no diagnostic or command output can land in the lock file.
    high = park(fd)
    if high is None and fd <= 2:
        os.close(fd)  # gives the slot back; the closed standard stream stays closed
        return unguarded(command, "no free descriptor above 2 for the lock")
    if high is None:
        high = fd
    else:
        os.close(fd)  # a closed standard stream the lock file had taken stays closed
    line = f"pid {os.getpid()} since {time.strftime('%H:%M:%S')}: {label}\n"
    try:  # the holder line is only information: failing to write it must not stop the command
        os.ftruncate(high, 0)
        os.write(high, line.encode("utf-8", "backslashreplace"))
    except OSError:
        pass
    if announced:
        warn(f"heavy-slot: got {path.name} after {time.monotonic() - started:.0f} s")
    os.set_inheritable(high, True)  # the command (same pid after exec) and its children keep the lock
    rc = become(command, path.name, pool, high)
    os.close(high)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
