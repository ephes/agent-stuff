"""heavy-slot: run a heavy command (full test suite, cold build) only while one of N shared slots is free.

Every worker on a machine (Codex jobs, merge clerks, Claude workers) wraps its heavy steps in
``heavy-slot -- <command>``. The slots are ``slot-<k>.lock`` files in one shared directory. heavy-slot
takes a free one with ``flock`` and then *becomes* the command (``exec``), passing the locked file
descriptor on. The command therefore has heavy-slot's pid, gets every signal directly and exits with
its own status, and the slot stays taken as long as any process holding that descriptor lives (the
command and the children it starts without closing inherited descriptors). The kernel releases the
lock when the last of them exits in any way, so a slot can never stay stale. A command that is already
inside a slot (``HEAVY_SLOT_HELD`` set) runs at once, so nested use cannot deadlock.

Python 3 stdlib only (3.9+). See README.md.
"""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import resource
import signal
import sys
import time
from pathlib import Path

DEFAULT_DIR = "~/.cache/heavy-slot"
DEFAULT_SLOTS = 3
DEFAULT_MAX_WAIT = 7200.0
POLL = 2.0
EX_TEMPFAIL = 75  # no slot within --max-wait
EX_USAGE = 2
EX_NOEXEC = 127
LOCK_FD_MIN = 200  # the inherited lock lives on a high descriptor, out of the way of `exec 3>&1` & co.


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
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
    p.add_argument("--slots", type=positive_int, default=None,
                   help=f"number of slots (HEAVY_SLOTS, default {DEFAULT_SLOTS})")
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


def try_acquire(paths: list[Path]) -> tuple[int, Path] | None:
    """An open fd holding the first free slot's lock, or None when all are taken."""

    for path in paths:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
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


def is_held(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def single_line(text: str) -> str:
    return "".join(char if char.isprintable() else " " for char in text).strip()


def holder(path: Path) -> str:
    """The holder line of a held slot (a free slot's file may still name its last holder)."""

    try:
        if is_held(path):
            with path.open(encoding="utf-8", errors="replace") as stream:
                return single_line(stream.read(200))
        return ""
    except OSError:
        return ""


def status(paths: list[Path]) -> int:
    for path in paths:
        line = holder(path)
        print(f"{path.name}\t" + (f"held\t{line}" if is_held(path) else "free"))
    return 0


def become(command: list[str], held: str) -> int:
    """Replace this process with ``command`` (returns only when it cannot be started)."""

    os.environ["HEAVY_SLOT_HELD"] = held
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
    return become(command, "none")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    slots = setting(args.slots, "HEAVY_SLOTS", DEFAULT_SLOTS, positive_int)
    max_wait = setting(args.max_wait, "HEAVY_SLOT_MAX_WAIT", DEFAULT_MAX_WAIT, nonnegative_finite_float)
    directory = Path(setting(args.dir, "HEAVY_SLOT_DIR", DEFAULT_DIR, str)).expanduser()
    if not args.status and not command:
        warn("heavy-slot: no command (usage: heavy-slot [options] -- COMMAND [ARGS...])")
        return EX_USAGE
    if os.environ.get("HEAVY_SLOT_HELD") and not args.status:
        return become(command, os.environ["HEAVY_SLOT_HELD"])  # nested: must not wait for itself
    paths = slot_paths(directory, slots)
    if args.status:
        return status(paths)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return unguarded(command, f"cannot create {directory}: {exc}")

    label = single_line((args.label or os.path.basename(command[0]))[:120])
    interval = min(POLL, max_wait / 4) if max_wait else POLL
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
        # The last retry falls just before the deadline; a wait suspended past it ends above.
        time.sleep(max(0.0, min(interval, max_wait - waited - 0.01)) if max_wait else interval)
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
    rc = become(command, path.name)
    os.close(high)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
