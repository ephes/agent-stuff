# workspace-gc

Inventories the git checkouts agents leave under `~/workspaces` and removes only
the ones that are provably safe to lose, plus the empty workspace directories
that removed checkouts leave behind. Dry run by default. Python 3 stdlib only,
no dependencies.

```sh
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc            # text report (dry run)
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc --json     # same, as JSON
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc --apply    # remove class A and empty workspace directories, prune stale worktree entries
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc remove <path>           # what would happen to one checkout
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc remove --apply <path>   # guarded removal of one checkout
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc report --out-dir DIR [--work-item SLUG]           # dry run, written to DIR
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc report --apply --out-dir DIR [--work-item SLUG]   # the scheduled job
```

`report` is the scheduled command. It does the same run as the default command
(`--apply` goes through the same code, with the same refusal and the same
re-checks per removal), but writes the result to `DIR/latest.txt` and
`DIR/latest.json` and, with `--work-item`, upserts that work-app item. See
[The scheduled job](#the-scheduled-job).

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
  way. If tips are still missing and some commits are not covered, every
  branch and tag of the remote is fetched into a private bare scratch
  repository under `$TMPDIR` (once per URL and run, deleted at the end of the
  run), and the count is repeated with its objects borrowed the same
  read-only way. Nothing is ever fetched into a checkout. Only if the fetch
  fails, or `--no-fetch` is given, does the result stay "containment
  unknown", not "unpushed". A clone with no remote at all is resolved through
  a repository with the same root commit;
- **supersession hints.** For each listed unpushed commit (up to 8 per
  checkout) the report says whether the remote's default branch has a commit
  with the same patch id (`git cherry`) or the same subject, e.g.
  `[same patch on main; same subject as main 335a535]`. The default branch
  comes from `ls-remote --symref`; its objects come from the checkout or the
  scratch fetch. Hints are information for the owner and never change a
  class;
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
- work-app items whose `worktree` field covers the path, closed items
  included (`work items --json`, with `~/.config/work/env`; skipped if that
  file does not exist). Work servers that list `worktree` answer this with the
  item list alone; for a list row without the `worktree` key (a server from
  before that field) the item is read with `work show --json <slug>`, one
  request per item. The item list must be provably complete. Servers before paging cap
  every list at 500 rows without saying so, so 500 rows without a `count` is
  treated as incomplete. With a paging server the `work` CLI follows every
  page; the result is incomplete if it says `truncated`, still carries a
  `next_cursor` (an older CLI that printed only the first page), has a `count`
  larger than the rows it returned, or has malformed (non-integer or negative) `count`/`truncated`
  fields. An incomplete list is reported as `work error (work items
  truncated: showing N of M ...)`, blocks `--apply`, and makes every checkout
  without a listed active item class D ("work item list incomplete"); the
  same holds when the work source fails outright;
- size (`du`), regenerable payloads with sizes (`build`, `.build`,
  `DerivedData`, `.venv`, `node_modules`, `target`, `dist`, ..., and any
  virtualenv, i.e. an ignored directory with a `pyvenv.cfg` such as
  `.venv311/`), device backups (`.cache/device-db-backups`,
  `device-preservation-*`), and ignored files that are *not* regenerable
  (for example a non-empty `db.sqlite3`, `.envrc`, benchmark `results/`). See
  [Regenerable ignored files](#regenerable-ignored-files).

## Regenerable ignored files

An ignored file or directory makes a checkout class C unless it is
regenerable. Regenerable are:

- a path component in the built-in name list (`__pycache__`, `.cache`,
  `.pytest_cache`, `site`, `.ansible`, ...) or matching `*.pyc`, `*.log`,
  `*.egg-info`, ...;
- a path matched by the built-in anchored patterns `tests/test_database.sqlite3*`
  (pytest-django's reusable test database and its fingerprint), `/uv.lock`,
  `test-media/` and `ansible/collections/`;
- anything inside a virtualenv (a directory with `pyvenv.cfg`);
- an **empty** entry: a 0-byte regular file, or a real directory holding
  nothing but directories and 0-byte regular files (no symlinks, at most
  2000 entries). A 0-byte `db.sqlite3` or an empty `var/piper/` is
  regenerable; a dev database with content is not;
- the extra patterns from `--regenerable PATTERN` (repeatable) and from the
  file `~/.config/workspace-gc/regenerable` (`--regenerable-file`, one
  pattern per line, `#` comments; it does not exist by default):
  - a plain name without `/` matches any path component, as before
    (`db.sqlite3` would match every dev database, so prefer a path);
  - a pattern with a `/` is anchored at the checkout root, like
    `.gitignore`: each component is a glob for exactly one path component
    (`*` never crosses a `/`), a leading `/` only anchors, and a trailing `/`
    matches directories only. A path inside a matched directory matches too.
    Examples: `tests/test_database.sqlite3*`, `cli/src/dds/_assets/*`,
    `.stage/`, `apps/ios-player/*.xcodeproj/`;
  - either form can be scoped to one repository as `REPO:PATTERN`, where
    REPO is the name of the network remote's repository
    (`git@github.com:ephes/podcast.git` -> `podcast`), e.g.
    `podcast:apps/ios-player/Rust/`.

A directory matched by a pattern (built-in or extra) that contains a `.git`
entry anywhere, i.e. a nested repository, is never regenerable.

Git reports a wholly ignored directory once (`var/`). If the directory as a
whole is not regenerable, the directory is walked on disk (not through git,
which leaves out `.git` metadata) and every entry that is not a real
directory - files, symlinks, symlinks to directories - must be regenerable
itself, so a pattern can name paths deeper than the directory git reported.
A `.git` entry anywhere in it, an unreadable directory or more than 200000
entries makes it unique. The removal re-check
evaluates the same rules again right before removing.

## Classes

| Class | Meaning | Examples |
|---|---|---|
| A | removable | clean, nothing unique, every commit on the network remote, idle |
| B | removable after push | like A, but some commits are on no network branch or tag; they are listed |
| C | needs owner | dirty, stash, device backups, non-regenerable ignored files, hidden index flags, submodules, grafts, read-only or unreadable parts, no or unreachable network remote, containment unknown, keep-listed, not inspectable |
| D | keep | in use, referenced by an active work item, work item list incomplete or unreadable, recently active (default 48h, `--min-idle-hours`), owns linked worktrees, objects borrowed by another repository, main checkout |

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

## Empty workspace directories

Removing a checkout leaves its workspace directory (`~/workspaces/ws-x/`)
behind. Every run also lists the direct children of the roots that hold
nothing: no file (a `.DS_Store` counts as a file), no symlink, only empty
directories, all on one filesystem. `--apply` removes them bottom-up with
`os.rmdir`, which cannot delete content: if anything has appeared in the
directory, the call fails and the directory stays. The check and the removal
both walk the tree through directory descriptors that do not follow symlinks,
so a directory swapped for a symlink stops the removal, and only the
directories the last check saw are removed: one created or replaced after it
stays, with its workspace. Directories with
content are not listed and never touched. A tree of more than 200 empty
directories is left alone.

An empty directory is kept, and listed with the reason, when

- it is named `ws-work-planning`, or it, a directory in it, or a path below it
  (a plain path, existing or not; a glob such as `ws-*/repo` when its leading
  segments match the directory and more follow) is on the keep-list;
- a process or herdr pane has its working directory in it. The process list is
  read again before each directory is removed, and a directory is kept when
  that read fails;
- an active work item names a worktree in it;
- it, or a directory in it, was created or changed less than 6 hours ago
  (`EMPTY_DIR_MIN_AGE_HOURS` in `workspace_gc/empties.py`). A worker may be
  about to clone into it. The age is the newest of creation, modification and
  status-change time.

The list is taken before the checkouts are removed, and removing a checkout
changes its workspace directory. So a directory emptied by a run is removed by
a later run, once it is 6 hours old.

## Workspace directories without a checkout

Every run also lists the direct children of the roots that hold no checkout
(none found by discovery) and are not empty, for example the review logs,
`review-*` directories and `.cache/uv` that a workspace keeps after its last
checkout is removed. For each it reports the total size, how much of it is
workspace-level caches (`.cache/uv`, `.cache/uv-tools`, `.cache/prek`,
`node_modules`), the number of other files, the top-level entries with sizes,
any git repository found anywhere inside (deeper than discovery looks), and
why it must not be touched (in use, an active work item, keep-listed or the
protected `ws-work-planning`; keep-listed and protected ones are not
inspected). Apart from the case below this is a report for the owner: the
tool never removes such a directory.

A directory that holds nothing but those workspace-level caches (no other
file, no git repository inside, nothing unreadable), is not kept for any of the
reasons above and has had no directory change for `--min-idle-hours` (default
48h) is `cache-only, removable`. With `--apply` the run deletes its cache
directories (`.cache/uv`, `.cache/uv-tools`, `.cache/prek`, `node_modules`),
each re-checked right before (fresh inspection, process working directories
read again). The empty shell stays and is removed by the empty-directory rule
once it is 6 hours old.

A directory named `ws-*` is `stale, removable` when it has no git repository outside
`.cache/uv`, is not kept for any of the reasons above (a keep-list entry
naming anything inside it counts), has nothing unreadable, and nothing in it
(files and directories) changed for `--min-stale-hours` (default 72; 0
disables the rule). With `--apply` the run deletes the whole directory,
review logs and notes included, after a fresh inspection and a fresh read of
the process working directories, through directory descriptors that do not
follow symlinks. Directories with a git repository elsewhere are never
touched. Every removed path and size is listed under "Removed in this run" in
`latest.txt` and in `husks_removed` in `latest.json`.

The summary line (also the work item's next action) ends with the number of
top-level directories under the roots and their approximate size.

## The scheduled job

The Studio runs `workspace-gc report --apply --out-dir
~/.local/state/workspace-gc --work-item workspace-gc-report` every day at 08:00
(LaunchAgent `de.wersdoerfer.workspace-gc`, managed in the owner's dotfiles).
Daily, because a class D checkout becomes class A once it has been idle for 48
hours. The job

- removes class A checkouts and empty workspace directories as described here,
  and prunes stale worktree entries. It never touches classes B, C and D;
- removes nothing at all when an in-use source cannot be read (see below). The
  report then starts with `REFUSED`, the exit code is 2, and the work item is
  handed to the owner;
- writes `latest.txt` and `latest.json`: what was removed in this run (count
  and disk), then what remains, with the reasons for B and C. A class A
  checkout that failed a re-check stays listed under A with that reason, and
  the exit code is 1;
- sets the work item's next action to the one-line summary, and withdraws the
  approval requests that earlier, report-only versions of the job opened.

To preview what the next run would do, run the same command without `--apply`
and with another `--out-dir` and no `--work-item`, so the last real report
stays in place:

```sh
~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc report --out-dir "$(mktemp -d)"
```

A checkout that must survive needs one of these: its path in the `worktree`
field of an active work item, an entry on the keep-list, or the uncommitted or
unpushed work that makes it class B or C.

## Removal guards

`--apply`, `report --apply` and `remove --apply` remove class A checkouts only
(the first two also empty workspace directories). Each removal re-checks the
following immediately before acting, and skips the checkout if any check fails:

- the path is a canonical, non-symlink directory strictly inside a root and
  not inside a main root, and it is still the top level of the checkout;
- `git status --porcelain -uall` is empty, no device backups exist, and HEAD
  has not moved;
- no index flags, submodules or grafts have appeared, and no non-regenerable
  ignored file has appeared;
- the containment check is repeated with a fresh `ls-remote` (no cache) and,
  if remote tips are missing locally, a fresh scratch fetch. Any git error,
  any unreachable remote (even when another remote covers HEAD) and any
  missing remote tip that leaves commits uncovered counts as unknown. That
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

`--apply` and `report --apply` refuse to run when an in-use source (herdr, processes, work app)
failed, returned partial results (`lsof` exiting non-zero, a truncated work
item list), or was turned off
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
tips, the keep-list, every removal guard under changed facts, the complete,
capped, truncated and paged shapes of the work item list, listed `worktree`
versus the per-item fallback for older servers, the scheduled command
(applied, refused, dry run), empty-directory removal with its guards, the
regenerable rules (empty entries, anchored and repository-scoped patterns,
virtualenvs), the scratch fetch (resolves containment without touching the
checkout, also in the removal re-check), supersession hints, and the
workspace directories without a checkout.

## Changes

See [CHANGELOG.md](CHANGELOG.md).
