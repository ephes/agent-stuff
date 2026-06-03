# Pi Review Loop — Design Spec

Status: draft for review
Date: 2026-06-03
Skill location: `claude/skills/pi-review-loop/` (a Claude Code skill)

## Problem

We want a Claude Code skill that runs a bounded review cycle: Claude implements a
change, hands the changed code to **Pi** as a fresh-context reviewer, and only
continues (commits) once Pi returns a clean review. If Pi reports issues, Claude
fixes them and re-reviews, up to a round cap.

The blocker today is not running Pi — it is that **a hung Pi is indistinguishable
from a working Pi**. With `pi --print`, output is buffered: the log stays at 0
bytes whether Pi is thinking, blocked, or dead. The driving Claude session
confidently reports "still working" while a session lingers (one ran 44 minutes).
Nothing self-terminates.

## The four confirmed "stuck" shapes

All four were observed in real sessions (llm-benchpacks, podcast, django-cast),
not hypothesized:

1. **M1 — Mid-run resource choke.** Pi tries to read a huge file in the inspected
   directory (a 425 MB transcript). Real CPU/IO-bound hang; no progress.
2. **M2 — Remote API block.** Pi is alive at ~0% CPU, blocked on the remote
   model API. With `--print` the log is 0 bytes — a pure mystery. Worsened by
   concurrent Pi sessions hammering the same API.
3. **M3 — Post-completion exit hang.** Pi *finishes* the review and writes its full
   verdict, then hangs on process exit in non-interactive mode. A driver waiting on
   process exit (or on `--print` to flush) waits forever on a review that is
   actually **done**. The work succeeded, but the naive signal (process alive)
   reads as failure.
4. **M4 — Abnormal exit with no output.** Pi exits or is killed (rate-limit backoff
   exhausted, provider error, or the harness auto-backgrounding the process) leaving
   a **0-byte file and no `agent_end`**. The process is *gone* but a content-only
   watcher (`until [ -s file ] && grep VERDICT …`) waits **forever** because it
   never checks whether the PID is still alive. The driver rationalizes the silence
   as "model latency" when nothing is running at all. This is the mirror image of
   M3: M3 is process-alive-but-done, M4 is process-dead-but-unfinished.

## Key insight

Stop using process exit / `--print` flush as the completion signal. Use the
**`--mode json` event stream** instead:

- Run `pi -p --mode json` with stdout redirected to a JSONL log file.
- **Completion** is the `agent_end` event in the log — not process exit.
- **Liveness** is log-file growth (mtime). No growth for `T` seconds = stalled.

This converts "is it stuck?" from a 44-minute guessing game into a one-line log
check. Combined with a **PID-liveness check**, it covers all four shapes:

- M1/M2 → process alive but no log growth for `T` → watchdog kills and fails the round.
- M3 → `agent_end` already in the log → extract verdict, kill the process
  proactively, treat as **success**. Never wait for it to exit.
- M4 → PID no longer alive and no `agent_end` in the log → abnormal exit → fail the
  round immediately (do not keep polling a dead process).

The monitor must therefore be a **4-way check**, never a content-only
`until [ -s file ]` loop: a dead process and an unfinished review both look like an
empty file, so liveness has to be probed explicitly.

## Locked decisions

- **Architecture:** Claude Code drives the loop; Pi is a fresh-context reviewer,
  launched detached (background) so Claude can poll the log without blocking.
- **Reviewer model:** latest available GPT, resolved at runtime. The active default
  in this environment is already `openai-codex` / `gpt-5.5`; the skill should
  confirm/select via `pi --list-models gpt` (or a `--model 'openai/gpt-5*'` glob)
  and fall back to a known-good pin if resolution fails.
- **Output mode:** `pi -p --mode json` → streamed JSONL log file. Never `--print`.
- **Concurrency:** one Pi review at a time. A lock/PID guard refuses to start a
  second review while one is live and clears stale locks. (Concurrency is what
  worsens M2.)
- **Scope:** changed files (the `git diff`) plus a size guard. Oversized files are
  skipped with an explicit logged note, never silently slurped (prevents M1).
- **Completion:** parse the verdict from the `agent_end` event, then **kill the
  PID** without waiting for exit.

## Verified Pi JSON event schema

From a smoke run (`pi -p --mode json --no-tools --no-session "…"`), each line is a
standalone JSON object. Observed sequence:

```
{"type":"session","id":"…","cwd":"…","timestamp":"…"}
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_start","message":{"role":"user",…}}
{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"…"},"message":{…}}
…
{"type":"turn_end","message":{…},"toolResults":[…]}
{"type":"agent_end","messages":[ …full final transcript… ],"willRetry":false}
```

Implications for parsing:

- **`agent_end`** is terminal and contains the full final `messages[]` array. The
  last `assistant` message's `text` content is the verdict — extract it directly,
  no delta reassembly needed. Example: `jq -c 'select(.type=="agent_end")'`.
- **`willRetry: true`** on an `agent_end` (or an error event) means Pi will retry
  (e.g. after an API error) — relevant to M2; the watchdog should keep watching, not
  treat it as final.
- Each assistant `message` carries cumulative **`usage`/`cost`** — the skill can
  report review cost as a bonus.
- Heartbeat keys off **log-file mtime**, not the embedded epoch `timestamp` fields
  (a hung process emits no new lines, so its own clock is irrelevant).

## The driver loop

```
preflight:
  - acquire lock (refuse if another pi-review is live; clear stale lock)
  - resolve reviewer model (latest GPT, else pinned fallback)
  - compute scope: git diff / changed paths; note files over size cap as skipped

for round in 1..N:
  - launch detached: pi -p --mode json --model <gpt> <scoped prompt> > log.jsonl
    record PID
  - monitor loop (poll every few seconds) — 4-way check, in this order:
      1. if agent_end present in log:
           extract final assistant text → parse verdict
           kill PID (do NOT wait for exit); break        # success path, covers M3
      2. else if PID not alive:
           mark round CRASHED (abnormal exit, no verdict); break   # covers M4
      3. else if (now - mtime(log)) > T:
           kill PID; mark round STALLED; break            # covers M1/M2
      4. else: keep polling
  - on STALLED/CRASHED: report which file/last-event was in flight (or the
    last log line / provider error); stop or retry once
  - parse verdict:
      CLEAN  → release lock; commit gate satisfied; done
      ISSUES → Claude fixes the listed items; continue to next round
  - if round == N and still ISSUES: stop, report unresolved items, do NOT commit

teardown (always): kill any surviving PID, release lock, leave log for inspection
```

**Process ownership.** The skill owns exactly one launch and one monitor. Do not
stack the harness's own Bash auto-backgrounding *and* a separate watcher process —
that spawns orphaned watchers nobody reaps (observed in the django-cast session).
Launch Pi once with a recorded PID and poll it directly; the monitor must reap the
process on every exit path (success, stall, crash, round cap).

## Reviewer prompt & verdict contract

- The skill sends Pi a focused, **read-only** review prompt scoped to the changed
  files, asking it to flag only issues affecting correctness or stated
  requirements (avoid over-engineering / nit floods).
- Pi must end its final message with a machine-parseable verdict the skill reads
  from the `agent_end` transcript, e.g. a final line:
  - `REVIEW: CLEAN` — no blocking issues, or
  - `REVIEW: ISSUES` followed by an enumerated list (severity + file + what).
- Because we parse the structured `agent_end` assistant message (not a scraped
  terminal pane), the old sentinel-echo / prompt-glyph / bracketed-paste failure
  classes from `docs/review-cycle-log.md` do not apply here. There is no TUI to
  drive and no pane to scrape.

## Tunable defaults

| Knob | Default | Rationale |
|------|---------|-----------|
| Stall timeout `T` | 180s of no log growth | gpt-5.5 can pause between events; lower risks false kills. |
| File size cap | 256 KB | Files larger are skipped + logged (prevents M1). |
| Max rounds `N` | 3 | Then stop and report rather than loop forever. |

All three are overridable as skill arguments.

## Non-goals

- No tmux, no pane scraping, no bracketed-paste delivery (those exist only because
  Claude Code is a heavy TUI; Pi is built for headless `-p`/json).
- Not a Pi-hosted workflow extension — Claude owns the loop.
- Not a Codex driver — this is a Claude Code skill specifically.
- Does not run concurrent reviews.

## To verify during implementation

- Exact behavior of `pi --list-models gpt` output format for "latest" selection.
- Whether an API error surfaces as a distinct event type vs only `willRetry` on
  `agent_end` (affects how the monitor distinguishes M2-retry from a real stall).
- Whether a read-only review needs any tool permission flags that could themselves
  block on stdin in `-p` mode (confirm tools run without an approval prompt; use a
  read-only tool allowlist if needed).
- A real review smoke against a small diff to confirm verdict extraction end to end.
- Pi's exit code on exhausted rate-limit backoff / provider error (M4): capture it on
  the PID-death path so a CRASHED round can report *why*, not just *that*, it died.
