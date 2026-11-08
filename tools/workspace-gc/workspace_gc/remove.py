"""Guarded removal of class-A checkouts.

Nothing here deletes a checkout that the inventory did not classify A in the
same run, and every removal re-checks the facts that make it safe right before
acting:

* the path is a real directory (not a symlink) strictly inside a root and
  still the top level of a git checkout;
* `git status` is empty (no changes, no untracked files);
* every commit is contained in a network remote, checked with a fresh
  `git ls-remote` (no cached answer); remote tips missing locally are fetched
  into a fresh private scratch repository, never into the checkout;
* no index entries flagged assume-unchanged/skip-worktree, no submodules,
  no grafts, no non-regenerable ignored files, and an exhaustive walk of the
  tree finds every directory readable and writable and no device backups;
* for standalone clones additionally: no stash, no linked worktrees, and no
  repository under the roots or main roots borrows its objects.

Any git error, unreachable remote or missing remote tip refuses the removal.

Worktrees go through `git worktree remove` without --force, so git itself
refuses one that gained changes in between. Standalone clones are emptied through inspected directory descriptors, then
removed by name after an identity check. Local safety checks run again after
remote and ownership verification.
"""

from __future__ import annotations

import os
import shutil
import stat

from . import git
from . import signals as sig_mod
from .husks import _fd_path
from .git import GitError
from .inventory import (Checkout, Inspector, _is_under, borrowers_of, deletion_scan,
                        hidden_state, keep_match, lending_scope, project_names, scan_ignored)


class Refused(Exception):
    pass


def _recheck_local(co: Checkout, roots: list[str], main_roots: list[str],
             keep_patterns: list[str], regenerable: list[str]) -> str:
    path = co.path
    if keep_match(path, keep_patterns) or (co.owner_repo and keep_match(co.owner_repo,
                                                                         keep_patterns)):
        raise Refused("keep-listed")
    if os.path.islink(path) or not os.path.isdir(path):
        raise Refused("path is gone or a symlink")
    real = os.path.realpath(path)
    if real != path:
        raise Refused("path is not canonical")
    if not any(_is_under(real, r) and real != r for r in roots):
        raise Refused("path is not inside a root")
    if any(_is_under(real, m) for m in main_roots):
        raise Refused("path is inside a main-checkout root")
    if os.path.islink(os.path.join(path, ".git")):
        raise Refused(".git is a symlink")
    top = os.path.realpath(git.out(["rev-parse", "--show-toplevel"], path).strip())
    if top != real:
        raise Refused(f"git toplevel is {top}")
    if git.out(["status", "--porcelain=v1", "-uall", "--ignore-submodules=none"], path).strip():
        raise Refused("checkout is dirty now")
    gdir = git.out(["rev-parse", "--path-format=absolute", "--git-dir"], path).strip()
    common = git.out(["rev-parse", "--path-format=absolute", "--git-common-dir"], path).strip()
    hidden = hidden_state(path, gdir, common)
    if hidden:
        raise Refused(hidden[0])
    blockers = deletion_scan(path)
    if blockers:
        raise Refused("; ".join(blockers[:3]))
    head = git.out(["rev-parse", "--verify", "HEAD"], path).strip()
    if head != co.head:
        raise Refused("HEAD moved since the inventory")
    _check_payload_state(co, path, real, regenerable, co.network_remotes)
    return real


def _check_payload_state(co, path, real, regenerable, urls):
    _, unique = scan_ignored(path, regenerable, project_names(urls))
    if unique:
        raise Refused("ignored files that are not regenerable: " + ", ".join(unique[:3]))
    if co.kind == "clone":
        if git.out(["stash", "list"], path).strip():
            raise Refused("stash present")
        listed = git.out(["worktree", "list", "--porcelain"], path)
        if any(block.strip() and os.path.realpath(block.splitlines()[0].split(" ", 1)[-1]) != real
               and "\nprunable" not in "\n" + block for block in listed.split("\n\n")):
            raise Refused("clone owns linked worktrees")


def _refs(path):
    return git.out(["for-each-ref", "--format=%(refname) %(objectname)",
                    "refs/heads", "refs/tags"], path)


def _recheck(co: Checkout, roots: list[str], main_roots: list[str],
             keep_patterns: list[str], regenerable: list[str], fetch: bool = True) -> str | None:
    real = _recheck_local(co, roots, main_roots, keep_patterns, regenerable)
    refs = _refs(co.path) if co.kind == "clone" else None
    path = co.path
    fresh = Inspector(main_roots, use_cache=False, keep_patterns=keep_patterns, fetch=fetch)
    try:
        _recheck_remote(co, path, real, fresh, roots, main_roots, keep_patterns, regenerable)
    finally:
        fresh.close()

    return refs


def _recheck_remote(co: Checkout, path: str, real: str, fresh: Inspector, roots: list[str],
                    main_roots: list[str], keep_patterns: list[str],
                    regenerable: list[str]) -> None:
    urls, alternates, _ = fresh.resolve_remotes(path)
    for u in co.network_remotes:
        if u not in urls:
            urls.append(u)
    if not urls:
        raise Refused("no network remote")
    _check_payload_state(co, path, real, regenerable, urls)
    if co.kind == "clone":
        lenders, unreadable = lending_scope(roots, main_roots, keep_patterns)
        if unreadable:
            raise Refused("cannot tell who borrows its objects: " + unreadable[0])
        borrowers = borrowers_of(path, lenders)
        if borrowers:
            raise Refused("objects borrowed (alternates) by " + ", ".join(borrowers))
        revs = ["HEAD", "--branches", "--tags"]
    elif co.kind == "worktree":
        revs = ["HEAD"]
    else:
        raise Refused(f"kind {co.kind} is never removed")
    # A clone resolved through a same-root sibling borrows that sibling's objects.
    alternates = list(dict.fromkeys(alternates + co.alternates))
    count, _, errors, missing, _ = fresh.unpushed(path, revs, urls, alternates)
    if errors:
        raise Refused("remote check failed: " + errors[0])
    if count:
        why = f"{missing} remote tip(s) missing locally, containment unknown" if missing \
            else (errors[0] if errors else "")
        raise Refused(f"{count} commit(s) not on a network remote" + (f" ({why})" if why else ""))


def _delete_clone(path, expected):
    if not shutil.rmtree.avoids_symlink_attacks:
        raise Refused("descriptor-safe deletion unavailable")
    parent, name = os.path.split(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open(parent, flags)
    try:
        if _fd_path(parent_fd) != parent:
            raise Refused("parent changed since inspection")
        child_fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            current = os.fstat(child_fd)
            if (current.st_dev, current.st_ino) != expected:
                raise Refused("clone replaced since inspection")
            for entry in os.listdir(child_fd):
                if stat.S_ISDIR(os.stat(entry, dir_fd=child_fd, follow_symlinks=False).st_mode):
                    shutil.rmtree(entry, dir_fd=child_fd)
                else:
                    os.unlink(entry, dir_fd=child_fd)
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != expected:
                raise Refused("clone replaced during deletion")
            os.rmdir(name, dir_fd=parent_fd)
        finally:
            os.close(child_fd)
    finally:
        os.close(parent_fd)


def remove_checkout(co: Checkout, roots: list[str], main_roots: list[str],
                    keep_patterns: list[str], regenerable: list[str] | None = None,
                    fetch: bool = True, signals: sig_mod.Signals | None = None) -> str:
    """Remove one class-A checkout. Returns a one-line outcome; raises Refused."""
    if co.cls != "A":
        raise Refused(f"class {co.cls}, only class A is removed")
    try:
        initial = os.stat(co.path, follow_symlinks=False)
        expected = (initial.st_dev, initial.st_ino)
        refs = _recheck(co, roots, main_roots, keep_patterns, regenerable or [], fetch)
        live = sig_mod.refresh(signals or sig_mod.Signals())
        blockers = live.apply_blockers()
        if blockers:
            raise Refused("in-use signals incomplete now: " + "; ".join(blockers))
        reason = sig_mod.protection_reason(co.workspace, live, work_path=co.path)
        if reason:
            raise Refused(reason)
        if co.kind == "clone" and _refs(co.path) != refs:
            raise Refused("refs moved during remote or ownership verification")
        _recheck_local(co, roots, main_roots, keep_patterns, regenerable or [])
        if co.kind == "worktree":
            git.out(["worktree", "remove", co.path], co.owner_repo)
            return f"removed worktree {co.path} (git worktree remove)"
        _delete_clone(co.path, expected)
        return f"removed clone {co.path}"
    except GitError as exc:
        raise Refused(str(exc)) from exc
    except OSError as exc:
        raise Refused(f"delete failed: {exc}") from exc


def prune(repo: str) -> list[str]:
    proc = git.run(["worktree", "prune", "-v"], repo)
    return [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
