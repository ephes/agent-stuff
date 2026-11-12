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

Keep-list: nothing is built in. Paths or globs can be added with `--keep` or in
`~/.config/workspace-gc/keep` (one per line, `#` comments). Keep-listed
checkouts are class C and are **not inspected at all**. No git command or `du`
runs on them, their alternates are not read, and local-origin chains and
root-commit lookups do not enter them. A worktree whose owning repository is
keep-listed is not removable, and that repository is never pruned. One
consequence: a keep-listed clone that borrows objects from a candidate clone
would go unseen. Keep-list whole workspaces, not single repositories, when
that matters.

At each destructive boundary, checkout, empty-directory and husk removal refresh
read-only work claims, herdr panes and finally process working directories.
Earlier protections are retained conservatively, including workspace-parent
claims; incomplete sources refuse removal. Each candidate costs a full work-item
list read and a pane read: there is deliberately no stale refresh cache. Older
work servers may require one detail read per item. Dry runs use one snapshot.
Direct remove_checkout callers must supply Signals with work configuration to
include work-claim protection; the CLI always does so.

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
- a process or herdr pane has its working directory in it. All three ownership sources
  are read again before each directory is removed; any failed read keeps it;
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
each re-checked right before (fresh inspection and all ownership sources
read again). The empty shell stays and is removed by the empty-directory rule
once it is 6 hours old.

A directory named `ws-*` is `stale, removable` when it has no git repository outside
`.cache/uv`, is not kept for any of the reasons above (a keep-list entry
naming anything inside it counts), has nothing unreadable, and nothing in it
(files and directories) changed for `--min-stale-hours` (default 72; 0
disables the rule). With `--apply` the run deletes the whole directory,
review logs and notes included, after a fresh inspection and a fresh read of
all ownership sources, through directory descriptors that do not
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

## Run time limits and the run lock

A run is bounded, so a slow filesystem, a stalled remote or a very full
`~/workspaces` cannot keep the daily job busy for more than a day (the run
started 2026-11-11 08:00 was still going after 29 hours: every clone removal
walked all of `~/workspaces` and `~/projects` again for borrowed objects,
~50s per walk under load, for hundreds of clones).

- **One step per checkout** (`--step-timeout SECONDS`, default 600): the
  inspection of one checkout, and the re-checks before one removal, are each a
  step. Filesystem walks check the deadline once per directory, git and du get
  at most the time left. A checkout whose inspection runs out of time is class
  C ("not inspectable: inspection ran out of time"); a removal whose re-checks
  run out of time is skipped. The deletion itself (`git worktree remove`, or
  emptying a clone) never runs under a deadline, so a limit never stops it
  half-way.
- **The whole run** (`--max-runtime MINUTES`, default 180, counted from the
  start of the process): checkouts not inspected by then are class C,
  removals not started by then are skipped ("not removed in this run: run
  time limit reached"), and so is everything after them that has not started:
  the informational local-remote notes, `git worktree prune` per repository,
  and the scan and the removal of each empty or stale workspace directory.
  The report is written as usual. With `--apply` the summary line says
  `stopped early: run time limit reached`, `latest.json` has `"stopped"`, and
  the exit code is 1; a scan cut short is listed as `INCOMPLETE:` in the
  report and under `"incomplete"` in `latest.json`. What can run past the
  limit is the one item under way (bounded by its step or its own timeouts,
  and a deletion is never interrupted), the reading of the in-use sources
  (below) and the report's work-app update.
- **Remote lookups are shared** by every checkout of a URL (`ls-remote`, the
  default branch, the scratch fetch) and their failures are cached for the
  run, so they run under their own timeout and the run deadline, not under
  what is left of the step of whichever checkout asked first.
- **One borrowed-objects walk per `--lending-ttl SECONDS`** (default 600)
  instead of one per removed clone. A repository that starts borrowing a
  clone's objects (`git clone --shared/--reference`) less than that long
  before the clone's removal can be missed (the age counts from the start of
  the walk); `--lending-ttl 0` walks for every
  removal as before. A walk that fails or runs out of time refuses the clone
  removals until the next walk.
- **Network waits are bounded:** `ls-remote` 45s, a scratch fetch 300s, ssh
  with `ConnectTimeout=15` and `ServerAliveInterval=15` (when no ssh command
  is configured), HTTP(S) transfers abort below 1 KB/s for 30s, and the
  in-use sources keep their own limits (herdr 30s, lsof 60s, work app 120s).
- **Bounded parallelism:** `--jobs` (default 8) is limited to 1-32.
- **Run lock** (`--lock-file`, default
  `~/.local/state/workspace-gc/workspace-gc.lock`): `report` and every
  `--apply` take an exclusive `flock` before reading anything. A second run
  that finds it held prints `BUSY, nothing done: another workspace-gc run
  holds ... (pid N, started ...)`, writes no report and exits 3. The kernel
  releases the lock when the holder exits, however it exits, so a killed run
  leaves nothing to clean up. A dry-run `scan` takes no lock.

## Removal guards

Checkout removal repeats local dirty/HEAD/hidden/ignored/stash/worktree
preconditions after remote and ownership verification; clones also compare
branch/tag refs. Linked worktrees do not compare shared sibling refs. Clone deletion binds the
inspected device/inode to an opened parent/child descriptor, empties only that
pinned directory, and checks its name again before rmdir. These guards refuse
substitutions and late local changes; they do not make concurrent filesystem
writes atomic.

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
  read-only checkout is reported and never partially deleted. The one
  exception is a read-only directory inside a **Go module cache**, see
  [Read-only Go module caches](#read-only-go-module-caches).

Worktrees are removed with `git worktree remove` (never `--force`), so git also
refuses one that changed in the meantime. The branch stays in the owning
repository. Clones are emptied through pinned directory descriptors and then removed with `rmdir`, which does not follow
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

## Read-only Go module caches

`go mod download` makes the directories of its module cache read-only (mode
0555) on purpose, so a plain recursive delete of a checkout or a workspace
directory that holds one (`.cache/go-mod`, `go/pkg/mod`, ...) stops half-way
with "Permission denied". A Go module cache is regenerable, so:

- the deletion walk does not count a directory as a blocker when it only
  misses the owner write bit, is owned by the current user, and is an
  extracted module of a Go module cache: at or below a `<module>@<version>`
  directory, not under the cache's own `cache/`. A Go module cache is
  recognised by its layout, not its name: a directory below the checkout or
  workspace directory (never that directory itself) holding `cache/download`
  (real directories, not symlinks);
- with nested caches the outermost one counts, in the deletion walk and in
  the unlock below alike;
- right before the delete of a checkout (clone or worktree), those
  directories get `u+w` (`chmod -R u+w` limited to them), walking through
  directory descriptors without following symlinks; this walk only runs
  when the deletion walk let such a directory through. A stale workspace
  directory removed whole gets the same treatment, before anything in it is
  deleted, when the inspection right before the removal found a directory
  without the owner write bit in it. Nothing else is ever chmodded, and a read-only
  directory anywhere else still keeps the checkout in class C ("cannot be
  deleted safely"). If `git worktree remove` refuses afterwards, the module
  directories stay writable; Go only reads them.

The Go module cache still has to be ignored and regenerable for the checkout
to be class A: `.cache/` is a built-in regenerable name, other locations need
a pattern (for example `REPO:go/`).

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
checkout, also in the removal re-check), supersession hints, the
workspace directories without a checkout, and bounded runs (step and run time
limits, the shared borrowed-objects walk, git cut off at a deadline, network
stall limits, `--jobs` bounds and the run lock), and read-only Go module
caches (made writable only inside the cache, symlinks not followed).

Partial apply runs retain successful removals and report each failed prune or
attempted empty/husk cleanup. Such runs exit 1; initial signal refusal exits 2.
Expected keeps are not failed attempts. JSON includes prune_errors and skipped
cleanup outcomes; text reports the same errors. Independent safe cleanup
continues after a prune failure. Removed clone paths are not pruned afterward.

Git safety commands remove inherited repository/object/index/namespace redirection
and command-line config injection variables. Explicit global/system config-file
selection and transport settings (GIT_SSH_COMMAND, GIT_SSH, SSH_AUTH_SOCK) remain
supported; each command receives its own environment copy. Caller alternates
are supplied only through the explicit wrapper argument. Local file URLs decode
URL paths once, accept empty/localhost authority, and refuse remote authorities,
queries, fragments, ambiguous double-leading-slash URL paths or invalid UTF-8/NUL paths.
Plain filesystem paths retain their existing semantics.

Timed Git commands run in an owned process group. Timeout or interruption sends
SIGTERM, allows a short lock-cleanup grace period, then kills remaining group
members and performs a bounded wait for Git (without draining inherited pipes); the caller's process group is never
signalled. Diagnostics are bounded. Direct wrapper contracts (environment copies,
argv boundaries, alternates and failures) run with `python3.14 -m unittest
tests.test_git` from this directory.

Human reports escape terminal controls and line separators in every data field;
structured JSON retains original paths, reasons and subjects. The human display
projection is not reversible; use JSON for exact identifiers. Class totals cover
remaining checkouts; removed_kb covers successfully removed checkouts only, while
husks_removed records whole-directory and cache-only bytes separately. Removed
husks are not also counted as remaining stale/cache-only candidates. Skipped
counts include failed attempted cleanups and prune errors, excluding initial
keeps. Refused runs report no removals; no-size scans may report zero sizes.
Report contract tests run with `python3.14 -m unittest tests.test_report`.

## Changes

See [CHANGELOG.md](CHANGELOG.md).
