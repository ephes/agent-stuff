# Pi Review Loop — Design Spec

Status: draft for review (revised after review round 1)
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

1. **M1 — Mid-run resource choke.** Pi reads a huge file in the inspected
   directory (a 425 MB transcript). Real CPU/IO-bound hang; no progress.
2. **M2 — Provider API block.** Pi is alive at ~0% CPU, blocked on the remote
   model API (or in a rate-limit backoff). With `--print` the log is 0 bytes — a
   pure mystery. Worsened by concurrent Pi sessions hammering the same API.
3. **M3 — Post-completion exit hang.** Pi *finishes* the review and writes its full
   verdict, then hangs on process exit in non-interactive mode. A driver waiting on
   process exit (or on `--print` to flush) waits forever on a review that is
   actually **done**. The work succeeded, but the naive signal (process alive)
   reads as failure.
4. **M4 — Abnormal exit with no output.** Pi exits or is killed (rate-limit backoff
   exhausted, provider error, or the harness auto-backgrounding the process) leaving
   a **0-byte file and no `agent_end`**. The process is *gone* but a content-only
   watcher (`until [ -s file ] && grep VERDICT …`) waits **forever** because it
   never checks whether the process is still alive. M4 is the mirror of M3:
   M3 is process-alive-but-done, M4 is process-dead-but-unfinished.

## Key insight

Stop using process exit / `--print` flush as the completion signal, and stop
polling for file *content*. Run a **single foreground harness script** that owns
Pi's whole lifecycle and reads its `--mode json` event stream directly:

- **Completion** is a terminal `agent_end` event whose verdict parses — not process
  exit.
- **Retries/backoff** are the `auto_retry_start` / `auto_retry_end` events — a
  documented backoff is not a stall.
- **Liveness** is two explicit probes: *is the process still alive?* and *how long
  since the harness last read a complete event?* (monotonic clock at read time, not
  file mtime).

This converts "is it stuck?" into deterministic state, covering all four shapes:

- M1/M2 → process alive, no new event for `T` (and not inside an `auto_retry`
  window) → kill the process group, fail the round.
- M3 → terminal `agent_end` with a parseable verdict → extract verdict, kill the
  process group, treat as **success**. Never wait for natural exit.
- M4 → process exited and no terminal `agent_end` seen → fail the round immediately
  with stderr + last event (do not keep polling a dead process).

## Locked decisions

- **Architecture:** Claude Code drives the *outer* loop (review → fix → re-review)
  because Claude holds the code context and does the fixing. Each *single review* is
  one invocation of a deterministic **foreground harness script** that owns Pi.
- **Reviewer model:** latest available GPT, resolved at runtime. `pi --list-models
  gpt` currently returns `openai-codex/gpt-5.5`; the harness selects the newest GPT
  (or a `openai/gpt-5*` glob) and falls back to a known-good pin if resolution fails.
- **Invocation:** `pi --mode json --no-session --no-tools --model <gpt> "<prompt>"`.
  - `--mode json` is already non-interactive and exits cleanly (verified both with
    and without `-p`), so `-p` is dropped as redundant.
  - `--no-session` so killing the process after `agent_end` cannot corrupt useful
    session state.
  - `--no-tools` by default (see Scope) — this, not a size number, is what actually
    prevents M1.
- **Concurrency:** one Pi review at a time, enforced by an **atomic** lock
  (`mkdir`- or `flock`-based, not a bare PID file) storing PID, cwd, started-at, and
  command. The lock is **global per user**, because the resource being protected is
  the shared provider API (the root cause of M2 under concurrency), not a per-repo
  resource. Stale locks (dead PID) are reclaimed.
- **Completion:** parse the verdict from the terminal `agent_end` event; if it does
  not contain an exact `REVIEW: CLEAN` / `REVIEW: ISSUES` verdict, the review is
  **invalid** (fail closed), never treated as clean.

## Verified Pi JSON event schema

From smoke runs (`pi --mode json --no-tools --no-session "…"`), each line is a
standalone JSON object. Observed/ documented event sequence and types:

```
session → agent_start → turn_start
  → message_start → message_update* → message_end
  → turn_end → agent_end
```

Documented event `type`s (Pi RPC/JSON docs) include: `agent_start`, `agent_end`,
`turn_start`, `turn_end`, `message_start`, `message_update`, `message_end`,
`tool_execution_{start,update,end}`, `queue_update`, `compaction_{start,end}`,
`auto_retry_{start,end}`, `extension_error`.

Implications for parsing:

- **`agent_end`** is terminal and carries the full final `messages[]` array. The
  last `assistant` message's `text` content is the verdict — extract it directly,
  no delta reassembly. Example: `jq -c 'select(.type=="agent_end")'`.
- **Retries:** `auto_retry_start` = `{attempt, maxAttempts, delayMs, errorMessage}`;
  `auto_retry_end` = `{success, attempt, finalError?}`. While inside a retry window
  the harness **suspends the stall timer** (honor `delayMs`). An `auto_retry_end`
  with `success:false` + `finalError` after `maxAttempts` is the M2 give-up signal →
  fail the round with that error.
- **Do not rely on `agent_end.willRetry`.** The docs place `willRetry` on
  `compaction_end`; installed Pi 0.78.0 happens to emit `willRetry:false` on
  `agent_end`, so it is version-dependent and unsafe. Use `auto_retry_*` instead.
- Each assistant `message` carries cumulative **`usage`/`cost`** — the harness can
  report review cost in `result.json`.

## The harness script

The skill ships a single foreground driver (e.g.
`claude/skills/pi-review-loop/bin/pi_review_loop.py`). Claude invokes it once per
review round and reads back a structured `result.json`; it never launches Pi in the
background or polls a log itself.

The harness:

1. **Preflight** — acquire the global lock (reclaim if stale); resolve the GPT model
   (else pinned fallback); assemble the review bundle (see Scope).
2. **Spawn** Pi in its **own process group**, capturing stdout (JSONL) and stderr.
3. **Monitor** — read stdout incrementally; for each complete JSON line:
   append to `events.jsonl`, update `last_event_at` (monotonic), and track
   `auto_retry` windows. Then evaluate, in order:

   ```text
   1. terminal agent_end with parseable verdict?
        → kill process group (TERM → grace → KILL), wait/reap
        → result = CLEAN | ISSUES(items)
   2. process exited (no terminal agent_end)?
        → wait/reap
        → result = CRASHED (include stderr tail + last event)         # M4
   3. not in an auto_retry window AND (now - last_event_at) > T?
        → kill process group (TERM → grace → KILL), wait/reap
        → result = STALLED (include last event / in-flight context)   # M1/M2
   4. else: keep reading
   ```

4. **Teardown (always)** — ensure the process group is reaped on every exit path
   (success, crash, stall, round cap); release the lock; leave logs for inspection;
   write `result.json`.

**Reap semantics (resolves "kill without waiting" vs "must reap"):** never block
waiting for Pi's *natural* exit (M3 means it may never come). But after taking a
kill action, do `SIGTERM` the group → short grace → `SIGKILL` if still alive →
`wait()` to collect status. Kill the **process group**, not the bare PID, because
the launch is wrapped (`/bin/zsh -c …`) and Pi may have children.

**Artifacts per review** (under a per-run dir): `events.jsonl`, `stderr.log`,
`result.json` (verdict, items, state, model, cost, timings, skipped files).

## Scope, tools, and the verdict contract

- **Default `--no-tools` + curated bundle.** The harness feeds Pi a bounded review
  bundle: diffstat, changed paths, the diffs, relevant doc/code excerpts, and an
  explicit list of files skipped for size. Because Pi has no `read`/`grep`/`find`/
  `ls`, it **cannot independently slurp a huge file**, which eliminates M1 at the
  source. (A size number alone does not: with tools, Pi could still open the
  skipped file.)
- **If tools are needed later**, allow only `--tools read,grep,find,ls`, ideally
  with Pi running in a sanitized temp directory containing just the bundle, not the
  real repo.
- **Read-only review prompt** scoped to the changed files; flag only issues
  affecting correctness or stated requirements (avoid nit floods / over-engineering).
- **Verdict contract.** Pi must end its final message with a machine-parseable
  verdict the harness reads from the `agent_end` transcript:
  - `REVIEW: CLEAN` — no blocking issues, or
  - `REVIEW: ISSUES` followed by an enumerated list (severity + file + what).
  - **Fail closed:** no exact match → `INVALID`, never `CLEAN`.
- **Scoped clean.** If any file/diff was skipped for size, a `CLEAN` verdict means
  "clean within the provided scope," not absolute clean; the harness records the
  skipped set in `result.json` and Claude surfaces that caveat.
- Because the harness parses the structured `agent_end` message (not a scraped TUI
  pane), the sentinel-echo / prompt-glyph / bracketed-paste failure classes in
  `docs/review-cycle-log.md` do not apply. There is no TUI to drive, no pane to
  scrape.

## Tunable defaults

| Knob | Default | Rationale |
|------|---------|-----------|
| Stall timeout `T` | 180s since last event (outside retry windows) | gpt-5.5 can pause between events; lower risks false kills. |
| File size cap | 256 KB | Larger files are excluded from the bundle + listed as skipped. |
| Max rounds `N` | 3 | Then stop and report unresolved items rather than loop forever. |

All three are overridable as skill arguments.

## Non-goals

- No tmux, pane scraping, or bracketed-paste delivery (artifacts of driving a heavy
  TUI; Pi is built for headless json).
- **No background-launch + separate watcher.** One foreground harness owns Pi;
  stacking harness auto-backgrounding with a watcher bash orphans processes
  (observed in django-cast).
- Not a Pi-hosted workflow extension — Claude owns the outer loop.
- Not a Codex driver — this is a Claude Code skill specifically.
- Not RPC mode — json mode's event stream is sufficient; RPC is overkill unless we
  later need interactive multi-prompt control of a single session.
- Does not run concurrent reviews.

## To verify during implementation

- `pi --list-models gpt` output format, for robust "newest GPT" selection.
- That `auto_retry_start`/`_end` actually bracket provider backoffs in practice, so
  the stall-timer suspension behaves (induce a transient error if feasible).
- Process-group kill/reap on macOS (`setsid`/new pgid at spawn; `kill -- -pgid`).
- A real review smoke against a small diff: end-to-end verdict extraction, the
  `INVALID` fail-closed path, and the scoped-clean caveat.
- Pi's exit code on exhausted backoff / provider error (M4): capture it on the
  process-exit path so a CRASHED round reports *why*, not just *that*, it died.
