# heavy-slot

Machine-wide cap for heavy commands (full test suites, cold dependency builds)
of parallel agent workers. Python 3 stdlib only.

```sh
H=~/projects/agent-stuff/tools/heavy-slot/bin/heavy-slot
$H -- just test                      # waits until one of 3 slots is free, then runs
$H --label "daybook gates" -- sh -c 'just lint && just typecheck && just test'
$H --slots 2 --max-wait 600 -- uv run pytest -n 4
$H --status                          # slot-0.lock  held  pid 123 since 18:02:11: just
```

Why: the Studio's load peaked at 897 (2026-11-08) and 714 (2026-11-17) with
up to 71 GB of swap (2026-11-07/08) when nine Codex jobs plus merge clerks ran
their full suites and cold `uv`/`npm` builds at the same moment. A worker
mostly waits on the model; only its test and build steps need the CPU. The
cap lets as many workers run as before while at most N of them run a heavy
step at once.

## Behaviour

- The slots are `slot-0.lock` … `slot-<N-1>.lock` in the slot directory.
  heavy-slot takes the first free one with `flock`, writes a holder line
  (`pid`, start time, label) into it and then *becomes* the command
  (`exec`), passing the locked descriptor on. There is no wrapper process:
  the command has heavy-slot's pid, receives every signal directly (Ctrl-C,
  a tool timeout, `kill`) and exits with its own status.
- A slot must be a regular file with exactly one filesystem link.
  heavy-slot rejects symlinks, hard-linked files and special files as
  unusable slots and continues trying the other slots. `--status` lists
  rejected entries as `unavailable` and
  reads holder metadata from the same descriptor it checks for a lock.
- The slot stays taken as long as any process holding that descriptor
  lives: the command and the children it starts without closing inherited
  descriptors (shell children do; Python's `subprocess` closes them by
  default). The kernel releases the lock when the last of them exits in any
  way, also `kill -9`, so a slot never stays stale. A daemon started from a
  shell inside the slot keeps the slot until it stops; `--status` then shows
  the original holder line.
- No free usable slot while a slot is held: one line on stderr (`no free slot, waiting (holders:
  …)`), then a retry every 2 s (every quarter of `--max-wait` when that is
  shorter). The last sleep is capped at the remaining wait time. A slot
  acquired after `--max-wait` seconds (e.g. by a waiter that was suspended) is given back:
  heavy-slot exits 75 and does not run the command; `--max-wait 0` waits
  forever. Both `--max-wait` and `HEAVY_SLOT_MAX_WAIT` require finite,
  nonnegative seconds. Invalid values are rejected before accessing slots or
  running the command.
- The command gets `HEAVY_SLOT_HELD=<slot file>`,
  `HEAVY_SLOT_HELD_DIR=<canonical pool directory>` and
  `HEAVY_SLOT_HELD_FD=<inherited descriptor>`. A nested call can reuse
  admission when the slot belongs to its requested pool and the descriptor
  still holds that slot. Directory symlink aliases refer to the same pool.
  A launcher that closes the lock descriptor makes its nested call go
  through normal acquisition, which can wait while the parent holds the slot.
- A slot directory that cannot be created, or a pool where every slot is
  unusable before the deadline, produces a `WARNING … running WITHOUT a slot` line,
  and the command runs (`HEAVY_SLOT_HELD=none`). Nested calls after an
  unguarded launch try to acquire a slot using their own settings. Warnings go to stderr
  and are lost when the caller closed it. The cap is a load brake;
  blocking a worker's gates because of a configuration slip would be worse.
- Right after it is taken, the lock descriptor is moved off the low
  descriptors: to the lowest free one at or above 200, else (descriptor limit
  below 200, or everything from 200 up in use) to the highest free one above
  2. This keeps it out of the way of scripts that reuse low descriptors
  (`exec 3>&1`), and a closed standard stream stays closed. If no move is
  possible it stays where it is when that is above 2; if it sits on fd 0-2,
  heavy-slot gives the slot back and runs the command without one (the
  second fail-open case, `WARNING` as above). A command that closes every
  inherited descriptor drops the slot early. SIGPIPE and SIGXFSZ get their
  default disposition back (Python ignores them).
- Exit codes of heavy-slot itself: 75 no slot in time, 127 the command
  cannot be started, 2 usage error. The holder line is information only: if
  it cannot be written (disk full), the command still runs.
- heavy-slot does not renice the command; the runners start their workers
  with `nice -n 5` (see below).

## Settings

| Option | Environment | Default |
|--------|-------------|---------|
| `--slots N` | `HEAVY_SLOTS` | 3 |
| `--dir PATH` | `HEAVY_SLOT_DIR` | `~/.cache/heavy-slot` |
| `--max-wait SEC` | `HEAVY_SLOT_MAX_WAIT` | 7200 |
| `--label TEXT` | | executable basename |

Both `--slots` and `HEAVY_SLOTS` accept integers from 1 through 64. Values
outside that range are rejected before constructing slot paths for either
status or acquisition.

The default label is the executable's basename. Labels are limited to
120 characters, with nonprintable characters replaced by spaces. An explicit
`--label` is visible in status and waiter diagnostics while the slot is held,
and remains in the lock file until the next command overwrites it. Use
non-sensitive text for explicit labels.

Every caller must use the same directory and slot count, or the cap is per
group. Three slots of `pytest -n 4` keep the 16-core Studio at about 12 busy
cores for tests while interactive work stays responsive.

## Use in the coordination runners

`~/workspaces/ws-work-planning/coordination` (not a git repository):

- `codex/run.sh` creates `~/.cache/heavy-slot`, passes it to Codex as a
  writable directory (`--add-dir`) and starts `codex exec` under `nice -n 5`;
  `codex/COMMON.md` tells Codex jobs to run full suites and cold builds
  through heavy-slot, with `pytest -n 4` at most, and to keep the shared
  `~/.cache/uv` instead of a per-job `UV_CACHE_DIR`.
- `katharina/run.sh` starts Claude workers and merge clerks under
  `nice -n 5`; `claude-common.md` and `katharina/_rules-common.txt` carry the
  same heavy-slot rule.

## Tests

```sh
cd tools/heavy-slot && python3.14 -m unittest discover -s tests -t .
```

Hermetic: a throwaway slot directory, real `flock` contention between
heavy-slot processes and the test process. The suite needs Python 3.11+;
the tool itself runs with 3.9+ (`/usr/bin/python3` included, which
sandboxes may resolve `python3` to).
