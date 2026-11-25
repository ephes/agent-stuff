# heavy-slot changelog

## Unreleased

- Recheck the slot name after confirming an inherited lock. If the entry
  changed, acquire normally and leave the outer command's descriptor alone.

- Verify the slot name after probing its lock and holder metadata. Report
  changed slots as unavailable and omit their holder lines from wait warnings.

- Preserve reused lock descriptors across exec, including after a launcher
  sets close-on-exec. Report a launch error if the descriptor cannot be made
  inheritable.

- Recheck the slot name and link count after locking. Release a lock on a
  changed slot and retry within the original wait budget.

- Skip unusable slots and keep using the remaining capacity. If all slots
  are unusable, retain the warning and unguarded execution.

- Bind nested admission to the requested slot pool, including symlink
  aliases of its directory.
- Validate the inherited lock descriptor before reusing admission. Acquire
  normally when the descriptor was closed or points to a different file.

- Limit `--slots` and `HEAVY_SLOTS` to 1–64 before constructing slot paths.

- Try to acquire a slot when a nested call inherits `HEAVY_SLOT_HELD=none`.

- Sleep for the remaining wait near the deadline so busy slots are
  not repeatedly probed in the final milliseconds.

- Admit only regular single-link slot files and read status metadata from
  the same descriptor used to check the lock.

- Use the executable basename as the default slot label. Keep labels on a
  single bounded line in slot files and diagnostics. Explicit labels remain
  in the lock file after the command exits.

- Reject negative and non-finite waits from `--max-wait` and
  `HEAVY_SLOT_MAX_WAIT` before accessing slots or running the command.

- New tool: `heavy-slot -- COMMAND` runs a heavy command (full test suite,
  cold build) only while one of N machine-wide `flock` slots is free
  (`HEAVY_SLOTS`, default 3; `~/.cache/heavy-slot`), so parallel workers no
  longer run all their suites at once (Studio load up to 897 and 71 GB of
  swap, 2026-11-07/08). heavy-slot `exec`s the command with the locked
  descriptor (moved to fd 200+, else the highest free fd above 2), so the
  command keeps its pid, signals and exit status, and the
  slot is held until the last process with the descriptor exits (released by
  the kernel, never stale). Nested calls run at once; `--max-wait` (7200 s,
  then exit 75; a slot acquired after it is given back); `--status`; fail-open with a
  warning when the slot directory is not usable, or when the lock landed on
  a standard descriptor (closed stdin/stdout/stderr) and cannot be moved above
  fd 2 (the slot is given back first).
