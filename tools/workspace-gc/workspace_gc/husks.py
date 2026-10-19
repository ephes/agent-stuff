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

import fnmatch
import os
import shutil
import stat
import time
from dataclasses import asdict, dataclass, field

from .empties import PROTECTED_NAMES, _keep_listed
from . import signals as sig_mod
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
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False,
                                                onerror=lambda e: errors.append(e.filename)):
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
        dirnames[:] = [d for d in dirnames if d != ".git"]
    if errors:
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


def _remove_payloads(path: str, root: str, payloads: list[str], whole: bool = False,
                     ino: int | None = None) -> str:
    """Delete the payload directories (relative to the workspace) below the
    workspace, reached from the root through descriptors opened with
    O_NOFOLLOW, so a path component swapped for a symlink stops the walk."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_fd = os.open(root, flags)
    except OSError as exc:
        return f"cannot open {root}: {exc.strerror or exc}"
    # Ancestors of the root could be symlinks swapped after the inspection:
    # the descriptor must still be where the root really is.
    actual = _fd_path(root_fd)
    if actual != root:
        os.close(root_fd)
        return (f"{root} now resolves to {actual}" if actual
                else f"cannot verify where {root} is; nothing removed")
    try:
        ws_fd = os.open(os.path.basename(path), flags, dir_fd=root_fd)
    except OSError as exc:
        os.close(root_fd)
        return f"cannot open {path}: {exc.strerror or exc}"
    if ino is not None and os.fstat(ws_fd).st_ino != ino:
        os.close(ws_fd)
        os.close(root_fd)
        return "replaced since the inspection"
    if whole:
        # Empty the pinned directory through its descriptor, then rmdir it:
        # a replacement of the name after the check is never descended into.
        try:
            for name in os.listdir(ws_fd):
                if stat.S_ISDIR(os.lstat(name, dir_fd=ws_fd).st_mode):
                    _rmtree_under(ws_fd, name)
                else:
                    os.unlink(name, dir_fd=ws_fd)
            os.rmdir(os.path.basename(path), dir_fd=root_fd)
        except OSError as exc:
            return f"removing {path} failed: {exc.strerror or exc}"
        finally:
            os.close(ws_fd)
            os.close(root_fd)
        return ""
    try:
        for rel in payloads:
            parts = rel.split("/")
            fds = []
            try:
                cur = ws_fd
                for part in parts[:-1]:
                    cur = os.open(part, flags, dir_fd=cur)
                    fds.append(cur)
                _rmtree_under(cur, parts[-1])
            except FileNotFoundError:
                continue
            except OSError as exc:
                return f"removing {rel} failed: {exc.strerror or exc}"
            finally:
                for fd in fds:
                    os.close(fd)
    finally:
        os.close(ws_fd)
        os.close(root_fd)
    return ""


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
        ino = os.lstat(h.path).st_ino
    except OSError as exc:
        return f"cannot stat {h.path}: {exc.strerror or exc}"
    fresh = inspect(h.path, sizes=True)
    _classify(fresh, min_idle_hours, min_stale_hours)
    h.kb, h.payload_kb = fresh.kb, fresh.payload_kb      # measured now, for the audit
    if fresh.stale:
        inside = _keep_inside(h.path, keep_patterns)
        if inside:
            return f"keep-listed path inside: {inside}"
        h.removed_what = "directory"
        return _remove_payloads(h.path, root, [], whole=True, ino=ino)
    if not fresh.removable:
        return "no longer cache-only and idle"
    h.removed_what = "caches"
    payloads = [rel for rel, payload in _entries(h.path) if payload]
    return _remove_payloads(h.path, root, payloads)


def remove(entries: list[Husk], roots: list[str], keep_patterns: list[str],
           sig: Signals, min_idle_hours: float = 48.0,
           min_stale_hours: float = 72.0) -> None:
    """Remove the stale husks (whole directory) and the caches of the
    cache-only ones, each re-checked right before, with the process working
    directories read afresh for every one. Updates the entries."""
    for h in entries:
        if not (h.removable or h.stale):
            continue
        cwds, status = sig_mod.read_process_cwds()
        if status.status not in ("ok", "absent"):
            h.outcome = f"process working directories unreadable now ({status.detail})"
            h.removable = h.stale = False
            continue
        live = Signals(herdr_cwds=sig.herdr_cwds, work_refs=sig.work_refs,
                       process_cwds=sorted(set(sig.process_cwds) | set(cwds)))
        h.outcome = _remove_one(h, roots, keep_patterns, live, min_idle_hours,
                                min_stale_hours)
        h.removed = not h.outcome
        h.removed_kb = (h.kb if h.removed_what == "directory" else h.payload_kb) if h.removed else 0
        if not h.removed:
            h.removed_what = ""
        h.removable = h.removable and h.removed
        h.stale = h.stale and h.removed
