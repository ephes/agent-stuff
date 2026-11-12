"""Read-only Go module caches.

`go mod download` leaves the module cache (GOMODCACHE, for example
`.cache/go-mod` or `go/pkg/mod`) with its directories at mode 0555 on
purpose, so a plain recursive delete stops half-way with "Permission
denied". A Go module cache is regenerable. Right before a removal, the
read-only directories inside one get the owner write bit back; nothing else
is ever chmodded.

A Go module cache is recognised by its layout, not its name: a directory
below the removal's top (never the top itself) that holds `cache/download`
(real directories, not symlinks); with nested caches the outermost counts. Inside it only the extracted modules
qualify, i.e. directories at or below a `<module>@<version>` component and
not under `cache/`; those are the ones `go` makes read-only. Directories
owned by someone else, or missing more than the owner write bit, never
qualify.
"""

from __future__ import annotations

import os
import stat


def _real_dir(path: str, dir_fd: int | None = None) -> bool:
    try:
        st = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode)


def _is_go_root(path: str) -> bool:
    cache = os.path.join(path, "cache")
    return _real_dir(cache) and _real_dir(os.path.join(cache, "download"))


def _module_part(rel: str) -> bool:
    """Whether a path relative to a Go module cache root lies at or below an
    extracted module (`<module>@<version>`), outside the cache's own
    `cache/` directory."""
    parts = rel.split(os.sep)
    return parts[0] not in ("cache", ".", "..") and any("@" in p for p in parts)


def go_mod_cache_root(dirpath: str, top: str, known: list[str] | None = None) -> str:
    """The outermost Go module cache root strictly between `top` and
    `dirpath` (`top` itself never counts), or "". Outermost, like `unlock`,
    which takes the first root its top-down walk reaches and does not look
    for nested ones, so both always judge a directory against the same root.
    `known` is a list of roots found so far: a path below one of them needs
    no further stat calls (an outermost root stays the outermost for
    everything below it), and a newly found root is appended to it."""
    cur = os.path.normpath(dirpath)
    top = os.path.normpath(top)
    if not cur.startswith(top + os.sep):
        return ""
    if known:
        for root in known:
            if cur.startswith(root + os.sep):
                return root
    parts = os.path.relpath(cur, top).split(os.sep)[:-1]
    probe = top
    for part in parts:
        probe = os.path.join(probe, part)
        if _is_go_root(probe):
            if known is not None:
                known.append(probe)
            return probe
    return ""


def in_go_mod_cache(dirpath: str, top: str) -> bool:
    """Whether `dirpath` is an extracted module directory (or below one) of a
    Go module cache that lies below `top`."""
    root = go_mod_cache_root(dirpath, top)
    return bool(root) and _module_part(os.path.relpath(dirpath, root))


def fixable(dirpath: str, top: str, known: list[str] | None = None) -> bool:
    """A directory below `top` that only misses the owner write bit and lies
    inside a Go module cache; `unlock` makes it deletable. Pass the same
    `known` list for every directory of one walk, so each cache root is
    looked up once."""
    try:
        st = os.lstat(dirpath)
    except OSError:
        return False
    return (stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid()
            and not st.st_mode & stat.S_IWUSR
            and os.access(dirpath, os.R_OK | os.X_OK, follow_symlinks=False)
            and _in_module(dirpath, top, known))


def _in_module(dirpath: str, top: str, known: list[str] | None) -> bool:
    root = go_mod_cache_root(dirpath, top, known)
    return bool(root) and _module_part(os.path.relpath(os.path.normpath(dirpath), root))


def unlock(dir_fd: int) -> int:
    """Give the owner write bit back to the read-only directories inside Go
    module caches below the directory open as `dir_fd` (`chmod u+w`), walking
    through descriptors without following symlinks. Directories outside a Go
    module cache, and directories owned by someone else, are left alone.
    Returns how many directories were changed; raises OSError if a chmod
    fails."""
    changed = 0
    roots: list[str] = []
    uid = os.geteuid()
    for dirpath, dirnames, _, fd in os.fwalk(".", dir_fd=dir_fd, follow_symlinks=False):
        rel = os.path.normpath(dirpath)
        root = next((r for r in roots if rel.startswith(r + os.sep)), "")
        if not root:
            # The top itself is never a cache root; a root below it is found
            # when the walk reaches it.
            if rel != "." and "cache" in dirnames and _real_dir("cache", fd) \
                    and _real_dir(os.path.join("cache", "download"), fd):
                roots.append(rel)
            continue
        if not _module_part(os.path.relpath(rel, root)):
            continue
        st = os.fstat(fd)
        if st.st_uid == uid and not st.st_mode & stat.S_IWUSR:
            os.fchmod(fd, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
            changed += 1
    return changed
