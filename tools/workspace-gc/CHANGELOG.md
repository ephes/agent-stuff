# workspace-gc changelog

## Unreleased

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
