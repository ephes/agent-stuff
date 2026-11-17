"""Workspace directories that hold no checkout ("husks"). Report only.

When the last checkout of a workspace (`~/workspaces/ws-x/`) is removed, the
directory often keeps review logs, `review-*` scratch dirs and tool caches
(`.cache/uv`, `.cache/prek`, `node_modules`). Such a directory is not empty,
so empties.py leaves it alone, and it has no checkout, so the inventory does
not list it. This module lists every direct child directory of the roots
without a checkout found by discovery, with its size, the share of
workspace-level caches (WORKSPACE_PAYLOADS) and what else is in it. Nothing
here deletes anything: the owner decides.

Two exceptions. A directory is `stale` when it has no git repository outside
`.cache/uv`, is not kept (in use, work item, keep list, protected), nothing in
it was changed for `min_stale_hours` (default 72) and nothing in it is
unreadable. `remove()` then deletes the whole directory (review logs and notes
included); `removed_what` says "directory". And a directory that holds nothing but workspace-level caches
(`cache_only`: no file outside them, no git repository, nothing unreadable),
is not kept (in use, work item, keep list) and whose directories were all last
changed at least `min_idle_hours` ago is `removable`. `remove()` deletes only
its WORKSPACE_PAYLOADS directories, each re-checked right before; the empty
shell stays and is removed by empties.py once it is old enough.

A git repository deeper than discovery looks (or inside a skipped payload
directory name) is listed under `git_dirs`, so a husk is never mistaken for
caches and logs only.
"""

from __future__ import annotations

import errno
import fnmatch
from contextlib import ExitStack
import os
import shutil
import stat
import time
from dataclasses import asdict, dataclass, field

from .empties import PROTECTED_NAMES, _keep_listed
from . import signals as sig_mod
from . import budget
from . import readonly
from .inventory import Inventory, _du_kb, _is_under, keep_match
from .signals import Signals

# Workspace-level directories that tooling rebuilds (relative to the workspace).
WORKSPACE_PAYLOADS = (".cache/uv", ".cache/uv-tools", ".cache/prek", "node_modules")
MAX_WALK = 2_000_000


@dataclass
class Husk:
    path: str
    kb: int = 0
    payload_kb: int = 0
    files: int = 0
    entries: list[dict] = field(default_factory=list)   # path, kb, payload
    git_dirs: list[str] = field(default_factory=list)   # repositories found inside
    kept: str = ""        # why it must not be touched (in use, keep-listed, ...)
    note: str = ""        # walk truncated or unreadable parts
    readonly_dirs: int = 0   # directories without the owner write bit
    cache_only: bool = False   # nothing but workspace-level caches
    idle_hours: float | None = None   # since the newest directory change (cache_only only)
    removable: bool = False    # cache_only, not kept, idle long enough
    removed: bool = False
    stale: bool = False        # whole directory removable (see module doc)
    removed_what: str = ""     # "directory" or "caches" once removed
    removed_kb: int = 0
    outcome: str = ""     # why removing the caches failed or was refused

    def to_dict(self) -> dict:
        return asdict(self)


def _is_real_dir(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _kept(path: str, keep_patterns: list[str], sig: Signals) -> str:
    if os.path.basename(path) in PROTECTED_NAMES:
        return "protected name"
    if keep_match(path, keep_patterns):
        return "keep-listed"
    for cwd in list(sig.process_cwds) + list(sig.herdr_cwds):
        if _is_under(cwd, path):
            return f"in use (working directory {cwd})"
    for ref in sig.work_refs:
        if ref.active and (_is_under(ref.worktree, path) or _is_under(path, ref.worktree)):
            return f"active work item: {ref.slug}"
    return ""


def _entries(path: str) -> list[tuple[str, bool]]:
    """(relative path, is payload) for the top-level content, with `.cache`
    split one level so its payload subdirectories stand on their own."""
    out = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return out
    for name in names:
        if name == ".cache" and _is_real_dir(os.path.join(path, name)):
            try:
                subs = sorted(os.listdir(os.path.join(path, name)))
            except OSError:
                subs = []
            if not subs:
                out.append((name, False))
            for sub in subs:
                rel = f"{name}/{sub}"
                out.append((rel, rel in WORKSPACE_PAYLOADS
                            and _is_real_dir(os.path.join(path, rel))))
        else:
            out.append((name, name in WORKSPACE_PAYLOADS
                        and _is_real_dir(os.path.join(path, name))))
    return out


def inspect(path: str, sizes: bool = True) -> Husk:
    h = Husk(path=path)
    payload_abs = {os.path.join(path, p) for p in WORKSPACE_PAYLOADS}
    errors: list[str] = []
    walked = 0
    try:
        st0 = os.lstat(path)
    except OSError as exc:
        h.note = f"unreadable: {exc}"
        return h
    device = st0.st_dev
    # Not a dataclass field (stays out of the report): the generation this
    # inspection walked, which removal compares with its own snapshots.
    h._walked = (st0.st_dev, st0.st_ino)
    h._walked_payloads = {}
    components = {".cache", *WORKSPACE_PAYLOADS}
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False,
                                                onerror=lambda e: errors.append(e.filename)):
        budget.check()
        # Check children before os.walk can descend into a mount; check the
        # current directory again in case it changed during descent. A child
        # that cannot be stat'ed (a readable but not searchable parent) is an
        # unreadable part: never descended into, and the note keeps the husk.
        skip = set()
        lost = False
        for name in [None] + dirnames:
            candidate = dirpath if name is None else os.path.join(dirpath, name)
            try:
                st = os.lstat(candidate)
            except OSError:
                errors.append(candidate)
                if name is None:
                    lost = True
                    break
                skip.add(name)
                continue
            if stat.S_ISDIR(st.st_mode) and st.st_dev != device:
                h.note = f"nested device boundary: {candidate}"
                return h
            rel = os.path.relpath(candidate, path)
            if rel in components and stat.S_ISDIR(st.st_mode):
                h._walked_payloads[rel] = (st.st_dev, st.st_ino)
        if lost:
            dirnames[:] = []
            continue
        if not os.access(dirpath, os.W_OK, follow_symlinks=False):
            h.readonly_dirs += 1
        walked += len(dirnames) + len(filenames)
        if walked > MAX_WALK:
            h.note = f"more than {MAX_WALK} entries, walk stopped"
            break
        if ".git" in dirnames or ".git" in filenames:
            h.git_dirs.append(os.path.relpath(dirpath, path))
        elif "objects" in dirnames and "refs" in dirnames and "HEAD" in filenames:
            h.git_dirs.append(os.path.relpath(dirpath, path))    # a bare repository
        # Caches are walked for repositories but their files are not counted.
        if not any(_is_under(dirpath, p) for p in payload_abs):
            h.files += len(filenames)
        dirnames[:] = [d for d in dirnames if d != ".git" and d not in skip]
    if errors:
        # Sizes stay informative: du cannot descend into unreadable trees
        # either, and the note alone keeps the husk from being removable.
        h.note = (h.note + "; " if h.note else "") + f"unreadable: {', '.join(errors[:3])}"
    for rel, payload in _entries(path):
        kb = _du_kb(os.path.join(path, rel)) if sizes else 0
        h.entries.append({"path": rel, "kb": kb, "payload": payload})
        if payload:
            h.payload_kb += kb
    h.kb = _du_kb(path) if sizes else 0
    return h


def _now() -> float:
    return time.time()


def _idle_hours(path: str, limit: float) -> float:
    """Hours since the newest change (modification or status change) of any
    directory in the tree, not following symlinks. Stops early once something
    younger than `limit` is found."""
    newest = 0.0
    now = _now()
    for dirpath, dirnames, _files in os.walk(path, followlinks=False):
        budget.check()
        try:
            st = os.lstat(dirpath)
        except OSError:
            continue
        newest = max(newest, st.st_mtime, st.st_ctime)
        if (now - newest) / 3600 < limit:
            break
    return max(now - newest, 0.0) / 3600


def _newest_change(path: str, limit_hours: float) -> float:
    """Hours since the newest change of anything in the tree (files, links and
    directories, not followed). Stops early once something is younger than
    the limit; an unreadable part counts as "now"."""
    now = _now()
    newest = 0.0
    bad = []
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False,
                                                onerror=bad.append):
        budget.check()
        for name in [""] + filenames + dirnames:
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                bad.append(name)
                continue
            newest = max(newest, st.st_mtime, st.st_ctime)
        if bad or (now - newest) / 3600 < limit_hours:
            return 0.0 if bad else max(now - newest, 0.0) / 3600
    return max(now - newest, 0.0) / 3600


def _uv_cache(rel: str) -> bool:
    return rel == ".cache/uv" or rel.startswith(".cache/uv/")


def _classify(h: Husk, min_idle_hours: float, min_stale_hours: float = 72.0) -> None:
    # Only workspace directories (`ws-*`): `.venv` or a hand-made directory
    # under the root is not one.
    h.stale = bool(os.path.basename(h.path).startswith("ws-")
                   and not h.kept and not h.note and min_stale_hours > 0
                   and not [g for g in h.git_dirs if not _uv_cache(g)]
                   and _newest_change(h.path, min_stale_hours) >= min_stale_hours)
    h.cache_only = (not h.kept and not h.files and not h.git_dirs and not h.note
                    and h.payload_kb > 0)
    if h.cache_only:
        h.idle_hours = _idle_hours(h.path, min_idle_hours)
        h.removable = h.idle_hours >= min_idle_hours


def scan(inv: Inventory, sig: Signals, sizes: bool = True,
         min_idle_hours: float = 48.0, min_stale_hours: float = 72.0) -> list[Husk]:
    """Direct child directories of the roots that hold no discovered checkout
    and are not empty (those are empties.py's)."""
    with_checkout = {co.workspace for co in inv.checkouts}
    empty = {e.path for e in inv.empty_dirs}
    found = []
    for root in inv.roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            path = os.path.join(root, name)
            if path in with_checkout or path in empty or not _is_real_dir(path):
                continue
            kept = _kept(path, inv.keep_patterns, sig)
            if kept in ("protected name", "keep-listed"):
                found.append(Husk(path=path, kept=kept))   # not inspected
                continue
            h = inspect(path, sizes)
            h.kept = kept
            _classify(h, min_idle_hours, min_stale_hours)
            found.append(h)
    return found


def _rmtree_under(parent_fd: int, name: str) -> None:
    """Delete the real directory `name` below the descriptor, without
    following symlinks anywhere (shutil.rmtree works through descriptors)."""
    shutil.rmtree(name, dir_fd=parent_fd)


def _empty(dir_fd: int) -> None:
    """Delete everything inside the directory open as `dir_fd`."""
    for name in os.listdir(dir_fd):
        if stat.S_ISDIR(os.lstat(name, dir_fd=dir_fd).st_mode):
            _rmtree_under(dir_fd, name)
        else:
            os.unlink(name, dir_fd=dir_fd)


def _fd_path(fd: int) -> str | None:
    """The real path of an open descriptor (macOS F_GETPATH, Linux /proc);
    None where the platform cannot say."""
    try:
        import fcntl
        return os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024)).split("\0")[0]
    except (ImportError, AttributeError, OSError):
        pass
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def _keep_inside(path: str, keep_patterns: list[str]) -> str:
    """The first path in the tree (directories, files, links; not followed)
    that a keep-list pattern matches, or ""."""
    if not keep_patterns:
        return ""
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            for pat in keep_patterns:
                if any(ch in pat for ch in "*?["):
                    if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, pat.rstrip("/") + "/*"):
                        return p
                elif _is_under(p, pat):
                    return p
    return ""


def _preflight_device(dir_fd: int, device: int) -> None:
    """Refuse the entire candidate before any unlink/chmod on boundary error.

    fwalk pins each visited directory; lstat checks children before descent,
    fstat checks the descriptor actually opened. Never follow symlinks, and
    propagate traversal errors instead of silently skipping an unreadable tree.
    """
    def failed(exc):
        raise exc

    for path, dirs, _, fd in os.fwalk(".", dir_fd=dir_fd,
                                      follow_symlinks=False, onerror=failed):
        budget.check()
        if os.fstat(fd).st_dev != device:
            raise OSError(errno.EXDEV, "nested device boundary", path)
        real = []
        for name in dirs:
            st = os.lstat(name, dir_fd=fd)
            if not stat.S_ISDIR(st.st_mode):
                continue    # fwalk lists directory symlinks and would open them
            if st.st_dev != device:
                raise OSError(errno.EXDEV, "nested device boundary", os.path.join(path, name))
            real.append(name)
        dirs[:] = real


def _identity(st) -> tuple[int, int]:
    return st.st_dev, st.st_ino


def _require_same(parent: int, name: str, child: int) -> None:
    st = os.lstat(name, dir_fd=parent)
    if not stat.S_ISDIR(st.st_mode) or _identity(st) != _identity(os.fstat(child)):
        raise OSError(errno.ESTALE, "replaced since the inspection", name)


def _remove_payloads(path: str, root: str, payloads: list[str], whole: bool = False,
                     ino: int | None = None, unlock: bool = False,
                     identity: tuple[int, int] | None = None,
                     payload_identities: dict[str, tuple[int, int]] | None = None) -> str:
    """Open and validate every selected directory before deleting anything.

    Pin workspace, payloads and their parents; empty only the admitted open
    directories and recheck their names before rmdir. No path component may
    be replaced by a real directory or symlink between inspection and use.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with ExitStack() as stack:
            def open_dir(name, parent=None):
                fd = os.open(name, flags, dir_fd=parent)
                stack.callback(os.close, fd)
                return fd

            root_fd = open_dir(root)
            actual = _fd_path(root_fd)
            if actual != root:
                return (f"{root} now resolves to {actual}" if actual
                        else f"cannot verify where {root} is; nothing removed")
            ws_name = os.path.basename(path)
            ws_fd = open_dir(ws_name, root_fd)
            st = os.fstat(ws_fd)
            if ((identity is not None and _identity(st) != identity)
                    or (ino is not None and st.st_ino != ino)):
                return "replaced since the inspection"
            if st.st_dev != os.fstat(root_fd).st_dev:
                return "workspace device boundary; nothing removed"
            opened = {"": ws_fd}
            links = [(root_fd, ws_name, ws_fd)]
            selected = []
            for rel in payloads:
                parts = rel.split("/")
                for i, part in enumerate(parts):
                    key = "/".join(parts[:i + 1])
                    if key in opened:
                        continue
                    parent = opened["/".join(parts[:i])]
                    child = open_dir(part, parent)
                    if (payload_identities is not None
                            and _identity(os.fstat(child)) != payload_identities.get(key)):
                        return "replaced since the inspection: " + key
                    opened[key] = child
                    links.append((parent, part, child))
                selected.append((opened["/".join(parts[:-1])], parts[-1], opened[rel]))
            # Validate all selections together: a later replacement must not
            # leave an earlier payload partially deleted.
            for parent, name, child in links:
                _require_same(parent, name, child)
            # Preflight the whole workspace, including every cache, before
            # any mutation. A later payload must not fail after an earlier
            # one was deleted, nor may Go-cache unlock cross a device.
            _preflight_device(ws_fd, st.st_dev)
            if whole:
                if unlock:
                    readonly.unlock(ws_fd)
                _empty(ws_fd)
                _require_same(root_fd, ws_name, ws_fd)
                os.rmdir(ws_name, dir_fd=root_fd)
            else:
                for parent, name, child in selected:
                    _require_same(parent, name, child)
                    _empty(child)
                    _require_same(parent, name, child)
                    os.rmdir(name, dir_fd=parent)
    except OSError as exc:
        return f"removing {path} failed: {exc.strerror or exc}"
    return ""


def _snapshot(path: str):
    """(workspace identity, selected caches, identities of every cache path
    component), or why the selection cannot be pinned. Raises OSError."""
    identity = _identity(os.lstat(path))
    payloads = [rel for rel, payload in _entries(path) if payload]
    payload_identities = {}
    for rel in payloads:
        parts = rel.split("/")
        for i in range(1, len(parts) + 1):
            key = "/".join(parts[:i])
            st = os.lstat(os.path.join(path, key))
            if not stat.S_ISDIR(st.st_mode):
                return "payload replaced before inspection: " + key
            payload_identities[key] = _identity(st)
    return identity, payloads, payload_identities


def _remove_one(h: Husk, roots: list[str], keep_patterns: list[str], sig: Signals,
                min_idle_hours: float, min_stale_hours: float) -> str:
    """Delete one husk (the whole directory if it is stale, else only its
    cache directories); returns "" or why not.
    Everything is decided again now, from a fresh inspection."""
    root = os.path.dirname(h.path)
    if root not in roots or not _is_real_dir(h.path):
        return "not a real directory directly under a root"
    now = _kept(h.path, keep_patterns, sig)
    if now:
        return now
    if _keep_listed(h.path, [(h.path, 0)], keep_patterns):
        return "a keep-list entry names something inside it"
    try:
        before = _snapshot(h.path)
    except OSError as exc:
        return f"cannot stat {h.path}: {exc.strerror or exc}"
    if isinstance(before, str):
        return before
    fresh = inspect(h.path, sizes=True)
    _classify(fresh, min_idle_hours, min_stale_hours)
    h.kb, h.payload_kb = fresh.kb, fresh.payload_kb      # measured now, for the audit
    if not fresh.stale and not fresh.removable:
        # The inspection's own reason (device boundary, unreadable part, walk
        # limit, new content) rather than an incomplete identity comparison.
        return ("no longer cache-only and idle" + (f": {fresh.note}" if fresh.note else ""))
    # Bind the deletion to the generation the fresh inspection walked: it
    # must have started on the snapshot's workspace and cache components,
    # and all of them must be unchanged after it (a rename away and back
    # around the inspection is refused).
    walked = getattr(fresh, "_walked_payloads", {})
    if (getattr(fresh, "_walked", None) != before[0]
            or any(walked.get(k) != v for k, v in before[2].items())):
        return "replaced during the inspection"
    try:
        after = _snapshot(h.path)
    except OSError as exc:
        return f"cannot stat {h.path}: {exc.strerror or exc}"
    if after != before:
        return "replaced during the inspection"
    identity, payloads, payload_identities = before
    if fresh.stale:
        inside = _keep_inside(h.path, keep_patterns)
        if inside:
            return f"keep-listed path inside: {inside}"
        h.removed_what = "directory"
        return _remove_payloads(h.path, root, [], whole=True, identity=identity,
                                unlock=fresh.readonly_dirs > 0)
    if payloads != [e["path"] for e in fresh.entries if e["payload"]]:
        return "caches changed during the inspection"
    h.removed_what = "caches"
    return _remove_payloads(h.path, root, payloads, identity=identity,
                            payload_identities=payload_identities)


def remove(entries: list[Husk], roots: list[str], keep_patterns: list[str],
           sig: Signals, min_idle_hours: float = 48.0,
           min_stale_hours: float = 72.0, expired=None) -> None:
    """Remove the stale husks (whole directory) and the caches of the
    cache-only ones, each re-checked right before, with all ownership sources
    read afresh for every one. Updates the entries. Once `expired()` is
    true, the entries not yet started stay (budget.TIME_LIMIT)."""
    for h in entries:
        if not (h.removable or h.stale):
            continue
        if expired is not None and expired():
            h.outcome = budget.TIME_LIMIT
            h.removable = h.stale = False
            continue
        live = sig_mod.refresh(sig)
        blockers = live.apply_blockers()
        if blockers:
            h.outcome = "in-use signals unreadable now: " + "; ".join(blockers)
            h.removable = h.stale = False
            continue
        h.outcome = _remove_one(h, roots, keep_patterns, live, min_idle_hours,
                                min_stale_hours)
        h.removed = not h.outcome
        h.removed_kb = (h.kb if h.removed_what == "directory" else h.payload_kb) if h.removed else 0
        if not h.removed:
            h.removed_what = ""
        h.removable = h.removable and h.removed
        h.stale = h.stale and h.removed
