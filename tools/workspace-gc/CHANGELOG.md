# workspace-gc changelog

## Unreleased

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
