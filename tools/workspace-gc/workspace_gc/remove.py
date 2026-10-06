"""Guarded removal of class-A checkouts.

Nothing here deletes a checkout that the inventory did not classify A in the
same run, and every removal re-checks the facts that make it safe right before
acting:

* the path is a real directory (not a symlink) strictly inside a root and
  still the top level of a git checkout;
* `git status` is empty (no changes, no untracked files);
* every commit is contained in a network remote, checked with a fresh
  `git ls-remote` (no cached answer);
* no index entries flagged assume-unchanged/skip-worktree, no submodules,
  no grafts, no non-regenerable ignored files, and an exhaustive walk of the
  tree finds every directory readable and writable and no device backups;
* for standalone clones additionally: no stash, no linked worktrees, and no
  repository under the roots or main roots borrows its objects.

Any git error, unreachable remote or missing remote tip refuses the removal.

Worktrees go through `git worktree remove` without --force, so git itself
refuses one that gained changes in between. Standalone clones are deleted with
shutil.rmtree, which does not follow symlinks.
"""

from __future__ import annotations

import os
import shutil

from . import git
from .git import GitError
from .inventory import (Checkout, Inspector, _is_under, borrowers_of, deletion_scan,
                        hidden_state, keep_match, lending_scope, scan_ignored)


class Refused(Exception):
    pass


def _recheck(co: Checkout, roots: list[str], main_roots: list[str],
             keep_patterns: list[str], regenerable: list[str]) -> None:
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
    _, unique = scan_ignored(path, regenerable)
    if unique:
        raise Refused("ignored files that are not regenerable: " + ", ".join(unique[:3]))
    blockers = deletion_scan(path)
    if blockers:
        raise Refused("; ".join(blockers[:3]))
    head = git.out(["rev-parse", "--verify", "HEAD"], path).strip()
    if head != co.head:
        raise Refused("HEAD moved since the inventory")
    fresh = Inspector(main_roots, use_cache=False, keep_patterns=keep_patterns)
    urls, alternates, _ = fresh.resolve_remotes(path)
    for u in co.network_remotes:
        if u not in urls:
            urls.append(u)
    if not urls:
        raise Refused("no network remote")
    if co.kind == "clone":
        if git.out(["stash", "list"], path).strip():
            raise Refused("stash present")
        wl = git.out(["worktree", "list", "--porcelain"], path)
        others = [b for b in wl.split("\n\n") if b.strip()
                  and os.path.realpath(b.splitlines()[0].split(" ", 1)[-1]) != real
                  and "\nprunable" not in "\n" + b]
        if others:
            raise Refused("clone owns linked worktrees")
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
    count, _, errors, missing = fresh.unpushed(path, revs, urls, alternates)
    if errors:
        raise Refused("remote check failed: " + errors[0])
    if count:
        why = f"{missing} remote tip(s) missing locally, containment unknown" if missing \
            else (errors[0] if errors else "")
        raise Refused(f"{count} commit(s) not on a network remote" + (f" ({why})" if why else ""))


def remove_checkout(co: Checkout, roots: list[str], main_roots: list[str],
                    keep_patterns: list[str], regenerable: list[str] | None = None) -> str:
    """Remove one class-A checkout. Returns a one-line outcome; raises Refused."""
    if co.cls != "A":
        raise Refused(f"class {co.cls}, only class A is removed")
    try:
        _recheck(co, roots, main_roots, keep_patterns, regenerable or [])
        if co.kind == "worktree":
            git.out(["worktree", "remove", co.path], co.owner_repo)
            return f"removed worktree {co.path} (git worktree remove)"
        shutil.rmtree(co.path)
        return f"removed clone {co.path}"
    except GitError as exc:
        raise Refused(str(exc)) from exc
    except OSError as exc:
        raise Refused(f"delete failed: {exc}") from exc


def prune(repo: str) -> list[str]:
    proc = git.run(["worktree", "prune", "-v"], repo, check=False)
    return [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
