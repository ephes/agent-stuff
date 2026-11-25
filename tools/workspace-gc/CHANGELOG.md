# workspace-gc changelog

## Unreleased

- Retire the run lock descriptor before releasing it so a failed close cannot
  cause a later release to touch a reused descriptor. Preserve the unlock
  error if closing also reports an OS error.

- Release the run lock before propagating an interruption while writing
  holder details, so a surviving caller can acquire it again.

- No running herdr server no longer blocks every run. Since the Studio reboot
  of 2026-11 no herdr server ran, `herdr pane list` failed with
  `server_not_running`, and every `report --apply` and `remove --apply` was
  refused (2152 removable checkouts, about 709 GB, piled up). That error code
  now means no herdr panes: herdr is reported as `absent (not running, treated
  as no panes: ...)`, after a direct connect to the named socket confirms that
  nothing listens there. Every other herdr failure still refuses the run.

- Finished Codex work no longer piles up in `~/workspaces` (954 top-level
  directories, about 526 GB, on 2026-11-18). A closed Codex job clone or a
  finished scout round clone now needs `--codex-idle-hours` (default 6, was a
  fixed 48) instead of `--min-idle-hours`; the runner, `autoround.sh` and the
  merge clerk pass 0 to `remove`. `ws-cx-<job>`/`ws-merge-<job>` of a closed
  job and `ws-cx-scoutN` of an archived round (`roundN.archived`, written by
  `autoround.sh` after copying the report and bundle lists) are stale after
  `--codex-stale-hours` (default 6) instead of 72, but only when no git
  repository at all is left in them (not even in `.cache/uv`); a
  `ws-cx-scoutN` without `roundN.archived` is kept. uv's marker files (the empty `.git`
  in uv's `sdists-vN` bucket whose parent holds a regular `CACHEDIR.TAG` with
  the standard signature; anything else stays a repository) are no longer taken for
  repositories (they made such directories "not inspectable" or blocked the
  stale rule), a `ws-cx-scoutN` without `roundN.archived` is never removed as
  an empty directory either, a closed job clone's removal re-reads its close
  record, and a linked worktree is never
  exempt inside `.cache/uv`. A file the owner cannot read (outside caches)
  keeps a directory like an unreadable directory does. `remove` waits for a
  held run lock (`--lock-wait`, default 1800 s, capped by `--max-runtime`)
  instead of exiting `BUSY` at once.

- Keep husks and cache-only workspaces containing nested device boundaries.
  Check admission and the entire pinned workspace before any deletion or
  Go-cache permission changes; refuse unreadable boundaries and workspaces
  mounted on a different device from their root. Same-device bind mounts
  remain outside this check. The deletion preflight does not open directory
  symlinks, so a link to an unreadable or remote directory inside a cache no
  longer refuses the candidate or touches the link target.

- Bind cache-only deletion to the inspected workspace, selected caches and
  parent directory identities through pinned descriptors. Refuse directory
  and symlink replacements before deleting any selected cache; recheck names
  before removing emptied directories. The removal snapshot must match the
  identities the fresh inspection walked and be unchanged after it, so a
  rename away and back around the inspection, or caches added or removed
  during it, cause refusal. A husk with unreadable parts (including
  directories that can be listed but not searched) keeps its sizes in the
  report, and a refusal names the fresh inspection's own reason.

- Codex job clones no longer pile up (431 of the 609 directories in
  `~/workspaces`, about 377 GB in all, were `ws-cx-*` on 2026-11-16). Codex jobs now keep their `codex-q/` branch
  local and a merge clerk records the job in `merged.txt` or `dropped.txt` of
  the coordination directory (`WORKSPACE_GC_CODEX_DIR`); a job clone
  (`ws-cx-<job>/<repo>`) listed there is class A when clean, without stash,
  not in use and idle for 48 hours, although its commits are on no remote.
  Legacy clones whose pushed branch the clerk merged and deleted are class A
  when the branch is gone from the remote and the default branch or
  `develop` has every local commit's patch (`git cherry`). A clone whose job
  is in neither file is never removed by this rule. Scout clones
  (`ws-cx-scoutN/<repo>`) stay class D until `scoutN.out` has a runner
  closeout. The removal re-check verifies the rule again; `latest.txt` shows
  the reason.

- Read-only Go module caches no longer stop a removal. `go mod download`
  leaves its module cache with directories at mode 0555, so deleting a stale
  workspace directory with `.cache/go-mod` failed with "Permission denied"
  (4 directories on 2026-11-12), and a checkout with one was class C
  ("cannot be deleted safely"). Extracted module directories (at or below
  `<module>@<version>`) of a Go module cache (a directory below the checkout
  or workspace directory holding `cache/download`) that only miss the owner
  write bit now get `u+w` right before the delete, through directory
  descriptors without following symlinks. Read-only directories anywhere
  else still block.

- Bounded runs. The daily run started 2026-11-11 08:00 was still running after
  29 hours because every clone removal re-walked all of `~/workspaces` and
  `~/projects` for repositories borrowing its objects (~50s per walk under
  load). That walk is now shared between removals for `--lending-ttl`
  seconds (default 600; 0 restores the per-removal walk). Inspection of one
  checkout and the re-checks before one removal are each limited to
  `--step-timeout` seconds (default 600; filesystem walks stop at the next
  directory, git and du get at most the time left; the deletion itself is
  never cut off), the whole run to `--max-runtime` minutes (default 180; then
  the remaining removals are skipped and the report is written with
  `stopped early`). Scratch fetches wait at most 300s (was 900s), du 300s
  (was 600s); ssh gets keep-alives and HTTP(S) a low-speed limit. `--jobs` is
  limited to 1-32. `report` and every `--apply` take a `flock` run lock
  (`--lock-file`); a second run exits 3 with `BUSY` instead of running next to
  or queueing behind a hung one.

- Escape control characters in human reports while retaining JSON identities;
  align partial-run summaries and exclude removed husks from removable counts.

- Terminate and reap owned Git process groups on timeout/interruption and
  bound failure diagnostics; add hermetic direct wrapper contracts.

- Isolate Git repository/config injection environment variables and decode
  local file URLs correctly, including escaped spaces and Unicode.

- Preserve partial-run receipts after prune errors and return failure for
  attempted empty/husk cleanup that could not complete; expected keeps stay successful.

- Bind clone deletion to inspected directory identity and repeat local dirt,
  HEAD, hidden-state and ignored-file checks after remote/ownership reads;
  branch/tag ref comparisons apply only to clones.

- Refresh process, pane and read-only work ownership before each removal;
  retain earlier claims and refuse incomplete refreshes across all removal kinds.

- The built-in keep entry for `ws-echoport-retention-race` is removed (its work
  is saved on a branch); the keep list is now empty unless configured.

- Work items are read from `work items --json` alone when the server lists
  `worktree` (work-ledger from 414e794 on): one paged list per run instead of
  one `work show --json` per item (~900 requests and subprocesses per run).
  Rows without the `worktree` key (older servers) are still fetched one by
  one. Completeness checks, closed-item notes and `--apply` guards are
  unchanged; a malformed row is a work source error.

- `--apply` removes `ws-*` workspace directories without a checkout whole (logs and
  notes included) when nothing in them changed for `--min-stale-hours` (72),
  they contain no git repository outside `.cache/uv` and are not in use,
  referenced by an active work item or keep-listed. Removed paths and sizes
  are in `latest.txt` and `latest.json` (`husks_removed`).
- The summary line ends with the number of top-level directories under the
  roots and their approximate size.
- `--apply` deletes the workspace-level caches (`.cache/uv`, `.cache/uv-tools`,
  `.cache/prek`, `node_modules`) of workspace directories without a checkout
  that hold nothing else, are not kept (in use, work item, keep list) and have
  been idle for `--min-idle-hours` (48h). Directories with logs or other files
  stay untouched and report-only.
- Fix: a keep-list glob such as `~/workspaces/*on-device-ad*` no longer
  protects every empty workspace directory (a pattern prefix matched all of
  them, so none was removed). A glob now protects only directories it matches.
- Empty ignored entries are regenerable: a 0-byte file (an empty
  `db.sqlite3`) or a directory holding only directories and 0-byte files (an
  empty `var/piper/`). A non-empty dev database stays class C.
- `--regenerable` accepts path globs anchored at the checkout root
  (`tests/test_database.sqlite3*`, `cli/src/dds/_assets/*`, trailing `/` for
  directories only) and a `REPO:` scope (`podcast:apps/ios-player/Rust/`).
  Plain names keep matching any path component. Patterns can also be listed
  in `~/.config/workspace-gc/regenerable` (`--regenerable-file`).
- Built-in anchored regenerable paths: `tests/test_database.sqlite3*`,
  `/uv.lock`, `test-media/`, `ansible/collections/`. Virtualenvs
  (`pyvenv.cfg`, e.g. `.venv311/`) are payload.
- A wholly ignored directory that is not regenerable as a whole is checked
  file by file, so patterns can name paths deeper than the directory git
  reports.
- "Containment unknown" is resolved by fetching the remote into a private
  scratch repository (never into the checkout), in the inventory and in the
  removal re-check. `--no-fetch` turns this off.
- Unpushed commits in B and C carry a hint: same patch id and/or same subject
  on the remote's default branch. Informational only.
- New report section: workspace directories without a checkout, with total
  size, workspace-level caches (`.cache/uv`, `.cache/uv-tools`,
  `.cache/prek`, `node_modules`), other entries and any git repository
  inside. Report only; nothing is removed.
