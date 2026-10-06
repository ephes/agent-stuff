# workspace-gc

Inventories the git checkouts agents leave under `~/workspaces` and removes only
the ones that are provably safe to lose. Dry run by default. Python 3 stdlib
only, no dependencies.

```sh
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc            # text report
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc --json     # same, as JSON
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc --apply    # remove class A, prune stale worktree entries
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc remove <path>           # what would happen to one checkout
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc remove --apply <path>   # guarded removal of one checkout
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc report --out-dir DIR [--work-item SLUG]
```

`report` is for the scheduled job: it writes `DIR/latest.txt` and
`DIR/latest.json` and, with `--work-item`, upserts that work-app item. It has no
`--apply`.

Sizes in the text report, the summary line and the work-app request are
human-readable like `du -h` (`512K`, `27M`, `1.3G`); `--json` keeps the raw
`kb` numbers.

## What each run looks at

Every run takes a fresh inventory. No saved report is reused. For every git
checkout under the roots (default `~/workspaces`, depth 3, symlinks never
followed), it records:

- the kind of checkout: a linked `worktree`, or a standalone `clone`;
- dirty state, counting untracked files; stashes (clones only, because a
  worktree's stashes live in its owning repository); and linked worktrees;
- branch, last commit, and the newest git or directory activity;
- **containment.** It checks whether every local commit (HEAD for a worktree;
  HEAD, branches and tags for a clone) is reachable from a branch or tag of the
  project's **network** remote, read live with `git ls-remote`. Local-path
  remotes (a clone of another checkout) are followed to the network remote,
  and their object stores are borrowed read-only through
  `GIT_ALTERNATE_OBJECT_DIRECTORIES`. If a remote tip's object is missing,
  other local repositories with the same root commit are consulted the same
  way. If tips are still missing and some commits are not covered, the result
  is "containment unknown", not "unpushed". A clone with no remote at all is
  resolved through a repository with the same root commit;
- `objects/info/alternates`: which repositories borrow objects from which.
  Every object store below the roots and the main checkouts (`~/projects`) is
  scanned to depth 6, including bare repositories and clones nested in other
  checkouts. Dependency payload directories and keep-listed paths are skipped,
  and a keep-listed lender's own alternates file is not opened. A directory
  that cannot be listed, or an unreadable alternates file, means nobody can
  tell who borrows from a clone, so no clone is removable;
- blind spots for `git status` and `rev-list`: index entries flagged
  assume-unchanged or skip-worktree, submodules, and grafts. Replacement refs
  are ignored (`GIT_NO_REPLACE_OBJECTS`), and fsmonitor and the untracked
  cache are turned off;
- in use: a herdr pane (`herdr pane list`) or a process working directory
  (`lsof`) anywhere in the checkout's top-level workspace directory;
- work-app items whose `worktree` field covers the path (`work items --json` /
  `work show --json`, with `~/.config/work/env`; skipped if that file does not
  exist);
- size (`du`), regenerable payloads with sizes (`build`, `.build`,
  `DerivedData`, `.venv`, `node_modules`, `target`, `dist`, ...), device
  backups (`.cache/device-db-backups`, `device-preservation-*`), and ignored
  files that are *not* regenerable (for example `db.sqlite3`, `.envrc`,
  benchmark `results/`).

## Classes

| Class | Meaning | Examples |
|---|---|---|
| A | removable | clean, nothing unique, every commit on the network remote, idle |
| B | removable after push | like A, but some commits are on no network branch or tag; they are listed |
| C | needs owner | dirty, stash, device backups, non-regenerable ignored files, hidden index flags, submodules, grafts, read-only or unreadable parts, no or unreachable network remote, containment unknown, keep-listed, not inspectable |
| D | keep | in use, referenced by an active work item, recently active (default 48h, `--min-idle-hours`), owns linked worktrees, objects borrowed by another repository, main checkout |

A work item counts as active unless its stage is `merged`, `installed`,
`accepted` or `dropped`. A closed item's worktree is reported as a note.

Keep-list: `~/workspaces/ws-echoport-retention-race` is built in and cannot be
turned off. More paths or globs can be added with `--keep` or in
`~/.config/workspace-gc/keep` (one per line, `#` comments). Keep-listed
checkouts are class C and are **not inspected at all**. No git command or `du`
runs on them, their alternates are not read, and local-origin chains and
root-commit lookups do not enter them. A worktree whose owning repository is
keep-listed is not removable, and that repository is never pruned. One
consequence: a keep-listed clone that borrows objects from a candidate clone
would go unseen. Keep-list whole workspaces, not single repositories, when
that matters.

## Removal guards

`--apply` and `remove --apply` remove class A only. Each removal re-checks the
following immediately before acting, and skips the checkout if any check fails:

- the path is a canonical, non-symlink directory strictly inside a root and
  not inside a main root, and it is still the top level of the checkout;
- `git status --porcelain -uall` is empty, no device backups exist, and HEAD
  has not moved;
- no index flags, submodules or grafts have appeared, and no non-regenerable
  ignored file has appeared;
- the containment check is repeated with a fresh `ls-remote` (no cache). Any
  git error, any unreachable remote (even when another remote covers HEAD) and
  any missing remote tip that leaves commits uncovered counts as unknown. That
  means skip, never a number;
- clones only: there is no stash and no linked worktree, and no repository
  under the roots or main roots borrows the clone's objects;
- an exhaustive walk of everything the removal would delete, including
  payload directories, finds every directory readable, writable and
  searchable, finds no traversal error, and finds no device backup. So a
  read-only checkout is reported and never partially deleted.

Worktrees are removed with `git worktree remove` (never `--force`), so git also
refuses one that changed in the meantime. The branch stays in the owning
repository. Clones are deleted with `shutil.rmtree`, which does not follow
symlinks. After removals, `git worktree prune` runs on the repositories that
own the inventoried worktrees and on the clones under the roots.

`--apply` refuses to run when an in-use source (herdr, processes, work app)
failed, returned partial results (`lsof` exiting non-zero), or was turned off
with `--no-*`. A source that does not exist on this
machine (no herdr, no work env file) is tolerated.

`remove <path>` does not apply the idle guard by default (pass
`--min-idle-hours`), because it is meant for a coordinator closing out an item
right after its merge. Every other guard still applies.

Limits: an agent that works in a checkout without a herdr pane, and without a
process whose working directory is in it, is detected only through the work
item's `worktree` field and the idle guard. Record worktrees on their items.

## Tests

```sh
cd ~/projects/agent-stuff/tools/workspace-gc
python3 -m unittest discover -s tests -t .
```

The tests build temporary repositories. A private `GIT_CONFIG_GLOBAL` rewrites
`git@net.test:` to local bare repositories, so the "network" remote,
`ls-remote`, clone and push all work offline. They cover the classes, the
local-origin chain and alternates handling, tag containment, missing remote
tips, the keep-list, and every removal guard under changed facts.
