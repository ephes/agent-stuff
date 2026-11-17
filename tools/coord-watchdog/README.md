# coord-watchdog

Deterministic checker for the coordination pipeline in
`~/workspaces/ws-work-planning/coordination`. Python 3 stdlib only; no LLM in
the normal path.

The coordinator session (Claude desktop app, `~/projects/matters`) stalls
silently now and then: a long turn, a question to the owner, a compaction. Its
scheduled checks fire only while it is idle, so nobody notices and the
pipeline idles. A launchd agent on the Studio runs this tool every 5 minutes;
it checks the pipeline and escalates each finding once.

```sh
tools/coord-watchdog/bin/coord-watchdog                 # one cycle (same as `check`)
tools/coord-watchdog/bin/coord-watchdog check -v        # also print info lines
tools/coord-watchdog/bin/coord-watchdog check --dry-run -v   # look only: no state, no escalation
tools/coord-watchdog/bin/coord-watchdog check --json
tools/coord-watchdog/bin/coord-watchdog restart-feeder  # the diagnosis run's only fix (see below)
```

Output: one tab-separated line per finding, `key<TAB>kind<TAB>detail`
(`-v` adds `# info` lines). Exit 0 no findings, 1 findings, 2 bad
configuration, 3 another check holds the lock.

## Checks

| Key | Kind | Finding when |
|-----|------|--------------|
| `feeder-dead` | `feeder-dead` | `codex/feeder.lock` names no live `feeder.sh` process and neither `codex/stop.flag` nor `codex/autoround.off` exists (those mark a deliberate pause) |
| `codex-queue-stalled` | `codex-queue-stalled` | `codex/queue.txt` has entries, the feeder runs, `codex/started.txt` has not changed for `QUEUE_STALL_MIN` and the last `feeder.log` line is not "quota guard refused" |
| `automerge-off` | `automerge-off-old` | `katharina/automerge.off` is older than `AUTOMERGE_OFF_MAX_MIN` |
| `stuck:<name>` | `worker-stuck` | a `katharina/run.sh <name>` process lives, and for `STUCK_MIN` neither `logs/<name>.log` nor `<name>.out` changed size nor did its process tree use `CPU_PROGRESS_SEC` of CPU |
| `unacked:<name>` | `report-unacked` | `katharina/<name>.out` is finished (no `run.sh <name>` process) for more than `ACK_MIN` and `acks/<name>` is missing or older than the report |
| `usage-stale` | `usage-stale` | `work usage status --max-age USAGE_MAX_AGE --provider P` exits 2 for a provider in `USAGE_PROVIDERS` |
| `usage-check` | `usage-check-failed` | that command fails otherwise (API down, no token) |
| `heartbeat` | `heartbeat-stale` | `coordinator.heartbeat` is missing or older than `HEARTBEAT_MIN` |
| `load` | `load-high` | the 5-minute load average stayed above `LOAD_THRESHOLD` for `LOAD_SUSTAIN_MIN` |

Notes:

- A headless `claude -p` writes its log (stderr) and `.out` (final message)
  only at the end, so both stay empty for the whole run. Growth alone would
  flag every worker after an hour; the CPU time of the worker's process tree
  (the `claude` process, its tool shells, test runs, review loops) is the
  second progress signal: `ps -S` (exited children folded into their
  parent), and only increases against the previous cycle are added up, so a
  tree total that drops when a child exits does not hide later work. A worker
  that only waits on a remote command (a
  long ssh deploy) for an hour can be reported; the diagnosis run looks at it.
- Katharina workers are `bash [.../]run.sh <name>` processes whose brief
  `katharina/<name>.md` exists (and no `codex/<name>.md`). Deferred starts
  (`bash -c 'until ...; ./run.sh x'`) do not count.
- Acknowledgement: the coordinator touches `coordination/acks/<name>` after it
  has handled `katharina/<name>.out` (merge clerk reports `merge-*.out`
  included). Reports finished before the watchdog's first cycle (`since` in
  the state) are ignored, so installing it does not flag the archive. A rerun
  of the same name needs a new touch.
- The coordinator touches `coordination/coordinator.heartbeat` on every
  periodic check (`coordinator-start`). The watchdog never reads session
  transcripts.
- Codex usage is not checked by default (`USAGE_PROVIDERS=claude`): Codex is
  off under the owner's Anthropic-only rule of 2026-11-17, and its old
  "Weekly · all models" reading would always be stale. Set
  `CW_USAGE_PROVIDERS=claude,codex` (or empty for all) when Codex runs again.

## Escalation

Per finding, deduplicated in `state.json`; a finding that disappears is
resolved and its state dropped (a recurrence is a new episode).

1. **(a) Message into the coordinator session**, when the finding is new and
   `MESSAGE_CMD` is set (the message is appended as its last argument). The
   Claude desktop app has no non-interactive CLI to post into a running
   session (checked 2026-11-17: `claude` 2.1.326 offers only background
   sessions of its own, `attach`/`logs`/`stop`), so this stage is empty by
   default and skipped.
2. **(b) One bounded diagnosis run**, once the finding has persisted for
   `ESCALATE_MIN`: a headless `claude -p --permission-mode auto --model
   DIAG_MODEL` with the brief `diag-brief.md` (findings filled in), on the
   same account `katharina/run.sh` would use (`katharina/account.main`
   holding a future epoch: the main account; otherwise
   `CLAUDE_CONFIG_DIR=~/.claude-katharina`), started from `~/workspaces` and
   killed (process group) after `DIAG_TIMEOUT_MIN`. It diagnoses read-only
   and may make one fix only: restart a dead feeder through
   `coord-watchdog restart-feeder`, which checks again that no feeder runs
   and neither `stop.flag` nor `autoround.off` exists, then starts
   `./feeder.sh >> feeder.log` with `FEEDER_ENV` (`BACKLOG_MAX=20
   BACKLOG_HOURS=48`, as documented in `coordinator-start`) in its own
   session, so the diagnosis run's timeout kill does not take the feeder
   along, and waits up to 15 seconds for its "feeder started" line (exit 0
   started, 1 refused, 2 no start line).
   It never starts or stops workers, edits flags, queue or briefs, touches the
   heartbeat or acks, answers owner requests or records ledger stages. Its
   final message, a German summary, lands in
   `watchdog/diag-<stamp>/summary.md` (`brief.md`, `claude.log`,
   `status.json`, `supervisor.log` beside it). One run per finding, at most
   one at a time, and at most one start per `DIAG_MIN_INTERVAL_MIN`. A
   finished run is closed out (stage c) before a new run may start.
3. **(c) Owner notification**, once per finding: when its diagnosis run has
   finished (with the summary and whether the findings are still open), or
   right away when no run was possible (`DIAG_ENABLED=0`, start failed, or
   rate-limited). There is no phone push channel for agents today (no ntfy,
   Pushover or similar in agent-stuff or the ops repos), so it goes to:
   - `watchdog/notifications.log` (always);
   - `herdr notification show` on the Studio (when `NOTIFY_HERDR=1`; best
     effort, shown in herdr);
   - a note on the work-app item `NOTIFY_WORK_ITEM` (`coord-watchdog`), which
     the owner sees in the work app (best effort; `work` loads its token from
     `~/.config/work/env`).

## Settings

Defaults below; override with `CW_<NAME>` environment variables or a
`--config FILE` of `NAME=VALUE` lines (environment wins).

| Name | Default | Meaning |
|------|---------|---------|
| `COORD_DIR` | `~/workspaces/ws-work-planning/coordination` | coordination directory |
| `STATE_DIR` | `<COORD_DIR>/watchdog` | state, logs, diagnosis runs |
| `STUCK_MIN` | 60 | minutes without progress before `worker-stuck` |
| `CPU_PROGRESS_SEC` | 20 | CPU seconds of a worker's process tree that count as progress |
| `ACK_MIN` | 30 | minutes a finished report may stay unacknowledged |
| `HEARTBEAT_MIN` | 45 | maximum heartbeat age |
| `AUTOMERGE_OFF_MAX_MIN` | 1440 | maximum `automerge.off` age |
| `QUEUE_STALL_MIN` | 120 | minutes a non-empty Codex queue may go without a start |
| `USAGE_MAX_AGE` | `1h` | passed to `work usage status --max-age` |
| `USAGE_PROVIDERS` | `claude` | comma list for `--provider`; empty checks every provider in one call |
| `LOAD_THRESHOLD` | 2.5 × CPU count | 5-minute load average limit (40 on the 16-core Studio) |
| `LOAD_SUSTAIN_MIN` | 30 | minutes above the limit before `load-high` |
| `ESCALATE_MIN` | 15 | minutes a finding persists before stage (b) |
| `DIAG_ENABLED` | 1 | 0 skips stage (b) and notifies directly |
| `DIAG_TIMEOUT_MIN` | 15 | hard limit of a diagnosis run |
| `DIAG_MIN_INTERVAL_MIN` | 60 | minimum gap between diagnosis starts |
| `DIAG_MODEL` | `claude-opus-5-5` | model of the diagnosis run |
| `MESSAGE_CMD` | empty | stage (a) command; empty skips it |
| `FEEDER_ENV` | `BACKLOG_MAX=20 BACKLOG_HOURS=48` | environment for `restart-feeder` |
| `NOTIFY_HERDR` | 1 | `herdr notification show` in stage (c) |
| `NOTIFY_WORK_ITEM` | `coord-watchdog` | work-app item for the stage (c) note; empty disables |
| `CLAUDE_BIN`, `WORK_BIN`, `HERDR_BIN`, `PYTHON_BIN` | `claude`, `work`, `herdr`, this Python | commands |
| `PS_OUT`, `LOADAVG`, `NOW` | empty | test hooks: `ps -axwwS -o pid=,ppid=,time=,command=` output file, load value, epoch |

## State files (`STATE_DIR`)

| File | Content |
|------|---------|
| `state.json` | `since` (first cycle), open findings with their stage, worker progress snapshots, load-high start, last diagnosis run |
| `latest.json` | last cycle: info lines and findings |
| `watchdog.log` | one line per cycle plus new/resolved findings and stage actions (rotated at 1 MB to `.1`) |
| `notifications.log` | every owner notification |
| `diag-<stamp>/` | one diagnosis run |
| `lock` | `flock` against overlapping cycles |

## Studio install

chezmoi (`~/.local/share/chezmoi`) manages the LaunchAgent
`de.wersdoerfer.coord-watchdog` (Studio only, `StartInterval` 300, log
`~/Library/Logs/coord-watchdog.log`) and its reload script
`run_onchange_after_reload-coord-watchdog.sh.tmpl`. After a change:
`chezmoi apply ~/Library/LaunchAgents/de.wersdoerfer.coord-watchdog.plist`
and run the reload script's commands (or a full `chezmoi apply`). The job runs
from `~/projects/agent-stuff`, so a merged change is live once that checkout
is fast-forwarded.

## Tests

```sh
cd tools/coord-watchdog && python3.14 -m unittest discover -s tests -t .
```

Hermetic: a throwaway coordination directory, a `ps` snapshot file, and stub
`work`, `herdr`, `claude` and `feeder.sh` scripts; the diagnosis-run tests
run the real supervisor against the stub and its timeout kill.
