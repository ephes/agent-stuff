"""Workspace directories that hold no checkout ("husks"). Report only.

When the last checkout of a workspace (`~/workspaces/ws-x/`) is removed, the
directory often keeps review logs, `review-*` scratch dirs and tool caches
(`.cache/uv`, `.cache/prek`, `node_modules`). Such a directory is not empty,
so empties.py leaves it alone, and it has no checkout, so the inventory does
not list it. This module lists every direct child directory of the roots
without a checkout found by discovery, with its size, the share of
workspace-level caches (WORKSPACE_PAYLOADS) and what else is in it. Nothing
here deletes anything: the owner decides.

A git repository deeper than discovery looks (or inside a skipped payload
directory name) is listed under `git_dirs`, so a husk is never mistaken for
caches and logs only.
"""

from __future__ import annotations

import os
import stat
from dataclasses import asdict, dataclass, field

from .empties import PROTECTED_NAMES
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


def scan(inv: Inventory, sig: Signals, sizes: bool = True) -> list[Husk]:
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
            found.append(h)
    return found
