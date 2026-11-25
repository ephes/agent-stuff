# tm-guard

A never-blocking Time Machine stall probe for the Studio. Python 3 stdlib
only. Work item `tm-stuck-phase-guard`.

On 2026-11-19 the Studio's backup to fractal stalled for 16 hours while
`tmutil status` kept showing `ThinningPostBackup`, and in the end `tmutil`
itself hung (ops-control `runbooks/time-machine-client-stall.md`). The
LaunchAgent `de.wersdoerfer.tm-guard` (chezmoi, Studio only) runs this probe
every 5 minutes and reports to macmini (`obs_ctl.py timemachine`, ops-deploy
`services.obs_daily`), whose status endpoint feeds Nyxmon's check "Studio
Time Machine progress" (ops-control `docs/OBSERVABILITY_ROUTINE.md`).

```sh
tools/tm-guard/bin/tm-guard            # one cycle: probe, keep state, report to macmini
tools/tm-guard/bin/tm-guard --dry-run  # print the report; no progress state, no report (lock and hung-tmutil record still apply)
tools/tm-guard/bin/tm-guard -v         # log the summary line even when unchanged
```

Exit 0 report kept on macmini, 1 report failed (logged), 3 run lock
unavailable. Log: `~/Library/Logs/tm-guard.log` (one line per change of the
summary, and every failure). State: `~/.local/state/tm-guard/`.

## What one cycle does

1. **`tmutil status -X`** in a child with a hard limit of 120 s (the
   runbook's "does not return within 2 minutes"). When the time is up the
   child gets SIGKILL by its own PID (no pattern, no process group) and 5 s
   to be reaped. Every child runs in its own session, so launchd's clean-up
   of the job's process group does not reach it either. The child is a
   small `sh` gate that `exec`s `tmutil` (same PID) only after reading a go
   line, which the probe writes once it has recorded the PID and the time
   in `hung.json`; a probe that dies before that closes the pipe and the
   gate exits without starting `tmutil`. The record is cleared once the
   child has been reaped. A child that still has not exited after the kill
   (a thread in an uninterruptible wait does not die), or one left by a
   probe that was stopped while it waited, keeps its record. The record
   holds the gate's start time as `TZ=UTC0 ps -o lstart=` prints it, taken before
   the go line (an `exec` keeps it), and is compared as text, so neither a
   clock step nor a time-zone or daylight-saving change confuses it. The
   120 s count from the moment the gate opens. While the PID shows
   that start time, or `ps` cannot tell (a timeout, any output on standard
   error, an unreadable answer), no further `tmutil` is started (the report
   says `hung`); the record is dropped once `ps` says the PID is gone (exit
   1, no output at all) or shows another start time. A record without a
   start time (`ps` failed at that moment) is kept while `ps -o ucomm=`
   shows `tmutil` or one of the gate's possible shells (`sh`, `bash`, `zsh`,
   `dash`; on macOS the waiting gate shows `bash`), or while `ps` cannot
   tell (no clean answer of 1 to 32 ASCII letters, digits or `_.+-`); it is
   dropped once the PID is gone or `ps` cleanly shows any other name (a
   reused PID).
   Results: `ok`, `timeout`, `hung`, `error` (not started, non-zero exit,
   unreadable output).
2. **Phase and progress** from the plist (a status without a readable
   `Running` flag is an `error`): `Running`, `Stopping`,
   `BackupPhase` (characters outside `[A-Za-z0-9_. -]` become `_`, as macmini
   accepts), `Percent` (`-1`, unknown, becomes null), bytes and files
   done and planned (`Progress`), `DateOfStateChange`. `Running` must be a
   plist boolean or the legacy integer 0 or 1. Other values make the
   status unreadable.
3. **`defaults read /Library/Preferences/com.apple.TimeMachine AutoBackup`**
   (20 s): `auto_backup` true, false or null. Automatic backups off is a
   normal state (the owner turned them off on 2026-11-20 and turns them on
   again after a watched manual run); the endpoint shows it as `state:
   disabled`, no rule fails on it.
4. **Band cross-check** on the backup server, read-only over SSH (60 s,
   `BatchMode`): the newest mtime of any file under the bundle's `bands/`
   and `mapped/`, as in the runbook:
   `ssh root@fractal.tailde2ec.ts.net "timeout -s KILL 50 bash -c 'set -o pipefail; find <bundle>/bands <bundle>/mapped -type f -printf \"%T@\n\" | sort -n | tail -n 1'"`
   (one quoted string: root's shell on fractal is fish; GNU `timeout` sends
   SIGKILL to the whole pipeline's process group on the server after 50 s,
   even when the SSH client is gone). A thinning or
   deletion phase shows no byte counter but writes bands.
5. **Progress tracking** (`state.json`): a running backup makes progress
   when the phase, a counter, the percent, `Stopping` or
   `DateOfStateChange` changes, or a band write is newer than the newest one
   seen in the current backup generation. The band baseline is reset when a
   backup starts after confirmed idle or when the `tmutil` destination UUID
   changes. Byte and file counts are kept as exact integers from zero up to (but
   excluding) 10¹⁶. Fractional and out-of-range counts are unavailable.
   `stalled_seconds` is the time since the last progress (0
   when no backup runs; a backup that was not running in the previous cycle
   starts at 0). While `tmutil` does not answer, the count carries on from
   the last known progress, and band writes still count. A wall-clock step
   back past the previous poll restarts the stall timer and keeps the last
   known backup status.
6. **The report** goes to macmini as root over SSH (100 s; `obs_ctl.py`
   waits up to 60 s for its lock). The progress state is kept even when the
   report fails.

The probe never touches the backup volume or `/Volumes`, and every command
it runs has a hard limit, so the whole cycle ends within about 5 minutes
even when everything hangs; launchd does not start a second copy while one
runs, and a manual run alongside exits 3. The probe also exits 3 if it cannot
lock a regular `run.lock` file or if the pathname no longer names that file
after acquisition.

The probe syncs the ownership record and its directory before allowing
`tmutil` to start. A publication failure closes the gate and reports a
probe error. Progress state uses the same durable JSON publication. A
live recorded process still blocks a new run when its timestamp is
unreadable. The diagnostic shows `unknown time` in that case.
Local JSON state reads accept regular files up to 64 KiB. Oversized,
non-regular or unreadable files use the missing-state fallback.

## Nyxmon rules

Check "Studio Time Machine progress" (service `observability-routine`,
`json-metrics` every 5 minutes; Nyxmon alerts on a critical after two
failed results in a row):

| Rule | Severity |
|------|----------|
| `$.timemachine.age_seconds < 1800` (the probe went silent for 30 minutes) | critical |
| `$.timemachine.tmutil_ok == true` (`tmutil status` timed out, hung or failed) | critical |
| `$.timemachine.stalled_seconds < 21600` (6 hours without progress) | critical |
| `$.timemachine.stalled_seconds < 7200` (2 hours without progress) | warning |
| `$.timemachine.cross_check_ok == true` (the band read failed while a backup runs) | warning |

When it alerts, follow ops-control `runbooks/time-machine-client-stall.md`
(decide "slow or stalled" on fractal; never kill `backupd` by pattern).

## Environment

`TM_GUARD_STATE` (state directory), `TM_GUARD_TMUTIL`, `TM_GUARD_DEFAULTS`,
`TM_GUARD_PS`, `TM_GUARD_SSH` (programs; the tests use stubs),
`TM_GUARD_BAND_HOST` (default `root@fractal.tailde2ec.ts.net`; empty skips
the band read), `TM_GUARD_BUNDLE` (default
`/fast/timemachine/studio.sparsebundle`), `TM_GUARD_HOST` (default
`root@macmini.tailde2ec.ts.net`), `TM_GUARD_CTL` (the `obs_ctl.py` command
on macmini).

## Tests

`cd tools/tm-guard && python3.14 -m unittest discover -s tests -t .`
(stub `tmutil`, `defaults`, `ps` and `ssh`; two tests inspect live child
processes with the real `/bin/ps`, the gate's process group and its `ucomm`,
so they need `/bin/ps` to be allowed, which a restrictive sandbox may deny).
