"""Leftover empty top-level workspace directories.

When a checkout is removed, its workspace directory (`~/workspaces/ws-x/`)
stays behind. This module finds the direct children of the roots that hold
nothing at all - no file, no symlink, only (nested) empty directories - and
removes them with `rmdir`, which cannot delete content: if anything appears
in the meantime the call fails and the directory stays. Both the check and the
removal walk the tree through directory descriptors opened without following
symlinks, so a path component swapped for a symlink stops the walk instead of
leading it out of the workspace.

A directory is kept when

* its name is protected (`ws-work-planning`, the coordinator's directory) or
  it, a directory in it, or a path below it is on the keep list;
* a process or herdr pane has its working directory in it;
* an active work item names a worktree in it;
* it, or a directory in it, was created or changed less than
  EMPTY_DIR_MIN_AGE_HOURS ago (a worker may be about to clone into it).
"""

from __future__ import annotations

import errno
import fnmatch
import os
import time
from dataclasses import asdict, dataclass

from . import signals as sig_mod
from .inventory import _is_under, keep_match
from .signals import Signals

# Younger than this (creation, modification or status change, whichever is
# newest, over the directory and everything in it): never removed.
EMPTY_DIR_MIN_AGE_HOURS = 6.0
# Never removed, whatever root they are found under.
PROTECTED_NAMES = frozenset({"ws-work-planning"})
# A tree of empty directories larger than this is left alone.
MAX_NESTED_DIRS = 200


@dataclass
class EmptyDir:
    path: str
    removable: bool = False
    removed: bool = False
    reason: str = ""            # why it is kept, or why removing it failed

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> float:
    return time.time()


def _open_dir(name: str, dir_fd: int | None = None) -> int:
    """A descriptor for a real directory; a symlink or anything else raises."""
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)


def _stamp(st) -> float:
    """Newest of creation (where the platform records it), modification and
    status-change time."""
    return max(st.st_mtime, st.st_ctime, getattr(st, "st_birthtime", 0.0))


class _NotEmpty(Exception):
    pass


def _inspect(fd: int, path: str, dev: int, dirs: list[tuple[str, int]]) -> float:
    """Add `path` (open as fd) and every directory below it to `dirs`, each
    with its inode, parents before children, and return the newest time stamp
    among them. Raises _NotEmpty for anything that is not a real directory on
    device `dev`, or a tree that is too large."""
    st = os.fstat(fd)
    if st.st_dev != dev or len(dirs) >= MAX_NESTED_DIRS:
        raise _NotEmpty
    dirs.append((path, st.st_ino))
    newest = _stamp(st)
    with os.scandir(fd) as it:
        names = [e.name for e in it]
    for name in names:
        try:
            child = _open_dir(name, fd)
        except OSError as exc:
            raise _NotEmpty from exc      # a file, a symlink, unreadable
        try:
            newest = max(newest, _inspect(child, os.path.join(path, name), dev, dirs))
        finally:
            os.close(child)
    return newest


def _rmdir_inspected(root_fd: int, root: str, dirs: list[tuple[str, int]]) -> None:
    """rmdir exactly the inspected directories, children first. Each one is
    reached from the root through descriptors that do not follow symlinks and
    must still be the inspected inode. A directory that appeared after the
    inspection is not in `dirs`, so the rmdir of its parent fails and the
    rest stays. Raises OSError at the first failure."""
    for path, ino in reversed(dirs):
        parts = os.path.relpath(path, root).split(os.sep)
        parent = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                nxt = _open_dir(part, parent)
                os.close(parent)
                parent = nxt
            fd = _open_dir(parts[-1], parent)
            try:
                if os.fstat(fd).st_ino != ino:
                    raise OSError(errno.ESTALE, "replaced since the inspection")
            finally:
                os.close(fd)
            os.rmdir(parts[-1], dir_fd=parent)
        finally:
            os.close(parent)


def _keep_listed(path: str, dirs: list[tuple[str, int]], keep_patterns: list[str]) -> bool:
    """The directory, a directory in it, or (for a plain path) a path below it
    is on the keep list."""
    if any(keep_match(d, keep_patterns) for d, _ in dirs):
        return True
    # A glob protects the directory only when its leading path segments match
    # the directory (each `*` kept inside one segment) and at least one more
    # segment follows, which can then name something below it
    # (`ws-*/repo`). Matching a pattern prefix with `*` crossing `/` would
    # protect everything: `~/workspaces/*on-device-ad*` starts with
    # `~/workspaces/*`, which matches every directory.
    parts = path.split(os.sep)
    for pat in keep_patterns:
        if any(ch in pat for ch in "*?["):
            segs = pat.rstrip(os.sep).split(os.sep)
            if len(segs) > len(parts) and all(
                    fnmatch.fnmatchcase(p, g) for p, g in zip(parts, segs)):
                return True
        elif _is_under(pat, path) or _is_under(os.path.realpath(pat), path):
            return True
    return False


def inspect(root_fd: int, root: str, name: str, keep_patterns: list[str],
            sig: Signals) -> tuple[str, list[tuple[str, int]]] | None:
    """None if the child `name` of the root is not an empty tree of
    directories. Otherwise (reason, directories): why it must stay, or "" if
    it may be removed, and the inspected directories with their inodes."""
    path = os.path.join(root, name)
    dirs: list[tuple[str, int]] = []
    try:
        fd = _open_dir(name, root_fd)
        try:
            newest = _inspect(fd, path, os.fstat(root_fd).st_dev, dirs)
        finally:
            os.close(fd)
    except (OSError, _NotEmpty):
        return None
    return _keep_reason(path, dirs, newest, keep_patterns, sig), dirs


def _keep_reason(path: str, dirs: list[tuple[str, int]], newest: float,
                 keep_patterns: list[str], sig: Signals) -> str:
    if os.path.basename(path) in PROTECTED_NAMES:
        return "protected name"
    if _keep_listed(path, dirs, keep_patterns):
        return "keep-listed"
    for cwd in list(sig.process_cwds) + list(sig.herdr_cwds):
        if _is_under(cwd, path):
            return f"in use (working directory {cwd})"
    for ref in sig.work_refs:
        if ref.active and (_is_under(ref.worktree, path) or _is_under(path, ref.worktree)):
            return f"active work item: {ref.slug}"
    age = (_now() - newest) / 3600
    if age < EMPTY_DIR_MIN_AGE_HOURS:
        return (f"created or changed {max(age, 0.0):.1f}h ago "
                f"(< {EMPTY_DIR_MIN_AGE_HOURS:g}h)")
    return ""


def scan(roots: list[str], keep_patterns: list[str], sig: Signals) -> list[EmptyDir]:
    """The empty direct children of the roots, each removable or with the
    reason it is kept. Directories with any content are not listed."""
    found = []
    for root in roots:
        try:
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            continue
        try:
            names = sorted(os.listdir(root_fd))
        except OSError:
            names = []
        try:
            for name in names:
                seen = inspect(root_fd, root, name, keep_patterns, sig)
                if seen is not None:
                    found.append(EmptyDir(path=os.path.join(root, name),
                                          removable=not seen[0], reason=seen[0]))
        finally:
            os.close(root_fd)
    return found


def _remove_one(e: EmptyDir, keep_patterns: list[str], sig: Signals) -> str:
    """Remove one entry; returns "" or why it stays. Everything is checked
    again now: the process working directories are read afresh, and the tree
    is inspected again, and only what that inspection saw is removed."""
    cwds, status = sig_mod.read_process_cwds()
    if status.status not in ("ok", "absent"):
        return f"process working directories unreadable now ({status.detail})"
    live = Signals(herdr_cwds=sig.herdr_cwds, work_refs=sig.work_refs,
                   process_cwds=sorted(set(sig.process_cwds) | set(cwds)))
    root, name = os.path.split(e.path)
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        return f"cannot open {root}: {exc.strerror or exc}"
    try:
        seen = inspect(root_fd, root, name, keep_patterns, live)
        if seen is None:
            return "no longer empty"
        reason, dirs = seen
        if reason:
            return reason
        _rmdir_inspected(root_fd, root, dirs)
    except OSError as exc:
        return f"rmdir failed: {exc.strerror or exc}"
    finally:
        os.close(root_fd)
    return ""


def remove(entries: list[EmptyDir], keep_patterns: list[str], sig: Signals) -> None:
    """Remove the removable entries, each re-checked right before its rmdir
    calls. Updates the entries in place."""
    for e in entries:
        if e.removable:
            e.reason = _remove_one(e, keep_patterns, sig)
            e.removed = not e.reason
            e.removable = e.removed
