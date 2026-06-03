# Pi Review Loop — Design Spec

Status: draft for review (revised after review round 5)
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
- **Reviewer model:** latest available GPT, resolved at runtime. Parse
  `pi --list-models gpt` (currently lists `openai-codex/gpt-5.5`), pick the highest
  semver-ish `gpt-*` row, and pass `<provider>/<model>` **exactly as listed** — do
  not assume an `openai/gpt-5*` glob, which can miss the actual provider prefix.
  Fall back to a known-good pin if resolution fails.
- **Invocation:** spawn Pi **directly** (no shell wrapper) with the bundle passed as
  an `@file`, not a giant argv string:
  ```
  pi --mode json --no-session --no-tools \
     --no-extensions --no-skills --no-prompt-templates --no-context-files \
     --append-system-prompt <reviewer instruction + verdict contract> \
     --model <provider/gpt> @<run-dir>/review-bundle.md
  ```
  The bundle (`@file`) carries only the diff/data; the reviewer role and the exact
  `REVIEW:` verdict contract are delivered via `--append-system-prompt` (live
  verification showed Pi emits no verdict without it).
  - `--mode json` is already non-interactive and exits cleanly (verified both with
    and without `-p`), so `-p` is dropped as redundant.
  - `--no-session` so killing the process after `agent_end` cannot corrupt session state.
  - `--no-tools` by default (see Scope) — this, not a size number, prevents M1.
  - `--no-extensions/--no-skills/--no-prompt-templates/--no-context-files` so
    extension startup errors and ambient project/global instructions cannot skew or
    wedge a deterministic review. Any relevant `AGENTS.md`/doc excerpts go into the
    bundle explicitly instead.
  - `@review-bundle.md` avoids argv length limits and makes runs reproducible.
  - **Subprocess env:** set `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` (both
    documented in Pi's README) to strip the `pi.dev` version check and telemetry from
    the monitored review path. Do **not** use `PI_OFFLINE=1` — it disables *all*
    startup network operations and its name implies more; the two targeted vars are
    unambiguous and leave the provider/model call untouched.
- **Concurrency:** one Pi review at a time, enforced by an **atomic** lock
  (`mkdir`- or `flock`-based, not a bare PID file), **global per user** because the
  protected resource is the shared provider API (the M2 root cause), not a per-repo
  resource. Lock metadata records: harness PID, Pi PID, **Pi PGID**, cwd,
  started-at, command/model, and run dir. Stale reclaim must guard against PID/PGID
  **reuse**: before killing an old group, verify identity — recorded command/model
  match, cwd/run-dir match, and start-time match where available — and tolerate
  `ESRCH` (group already gone). Only then `killpg` the old **process group**.
- **Completion:** parse the verdict from the **final assistant message** in the
  terminal `agent_end` event — never from the whole transcript (the transcript
  echoes the user prompt/bundle, which contains verdict *examples*; scanning it
  would let prompt text masquerade as a verdict). If the final assistant text has no
  exact verdict, the review is **invalid** (fail closed), never treated as clean.

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

- **`agent_end`** is terminal and carries the full final `messages[]` array — so no
  delta reassembly is needed. The verdict comes from the **last `assistant` message**
  only (see the verdict contract for the exact content-block extraction shape), not
  the whole `messages[]` array. Example: `jq -c 'select(.type=="agent_end")'`.
- **Retries:** `auto_retry_start` = `{attempt, maxAttempts, delayMs, errorMessage}`;
  `auto_retry_end` = `{success, attempt, finalError?}`. While inside a retry window
  the harness **suspends the stall timer** — but with a bound, so a retry that never
  ends is not an infinite blind spot:
  `retry_deadline = auto_retry_start_at + delayMs + retry_grace`, also capped by the
  overall `global_deadline`. No matching `auto_retry_end` by `retry_deadline` →
  `STALLED_RETRY` (kill/reap/fail). An `auto_retry_end` with `success:false` +
  `finalError` after `maxAttempts` is the M2 give-up signal → fail with that error.
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
2. **Spawn** Pi directly in its **own session/process group**, e.g.
   `subprocess.Popen([...], start_new_session=True, stdout=PIPE, stderr=PIPE)` — no
   `/bin/zsh -c` wrapper (shell wrapping reintroduces quoting bugs and process-tree
   ambiguity). **Cache the PGID immediately after spawn** (`os.getpgid(proc.pid)`);
   do not call `getpgid` late, after exit, when the PID may be gone. Kill via
   `os.killpg(cached_pgid, SIG…)`, tolerating `ESRCH`. Initialize `last_event_at`
   and the `global_deadline` at spawn time (not at first event), so a Pi that emits
   nothing is still subject to both timers.
3. **Monitor** — the loop must **never block on `readline()`**: M1/M2 are precisely
   "no new line arrives," so a blocking `for line in proc.stdout` would never reach
   the stall/liveness checks. Use non-blocking pipe reads (`selectors`/`select`) or
   a reader thread, plus a periodic timer tick. Read **stdout and stderr
   concurrently** (or redirect stderr straight to `stderr.log`) so a full stderr
   pipe can't deadlock Pi into a harness-induced stall. Every raw stdout line is
   teed to `stdout.raw.log`; then try to parse JSON. A **valid** event is appended to
   `events.jsonl` (keeping it strict JSONL for `jq`/postmortem). A **malformed/
   non-JSON line** (startup or provider bug leaking into the stream) must never crash
   the harness and does **not** count as a valid event — record it as
   `{"type":"malformed_stdout","raw":"…"}` in `events.jsonl` (so the file stays valid
   JSONL) and continue; if no valid `agent_end` ever arrives, the round is
   `CRASHED`/`INVALID`, never `CLEAN`. For each valid event: update `last_event_at`
   (monotonic) and track `auto_retry` windows + `retry_deadline`. On each tick/line
   evaluate, in order:

   ```text
   1. terminal agent_end with parseable verdict?
        → kill process group (TERM → grace → KILL), wait/reap
        → result = CLEAN | ISSUES(items)
   2. terminal agent_end WITHOUT an exact verdict?
        → kill process group, wait/reap
        → result = INVALID (fail closed — never CLEAN)
   3. process exited?
        → first do a SHORT, BOUNDED, NONBLOCKING drain of available stdout+stderr
          (a child may hold the pipe open, so the drain must not block forever),
          parse any final complete lines AND any valid final unterminated line
          (nonblocking assembly often leaves a buffered last object when the process
          exits without a trailing newline), THEN:
            parseable verdict in final assistant text → CLEAN | ISSUES
            agent_end without verdict                 → INVALID
            neither                                   → CRASHED (stderr tail + last event)  # M4
        → wait/reap
   4. auto_retry_end with success:false (provider gave up after maxAttempts)?
        → kill process group if still alive, wait/reap
        → result = PROVIDER_ERROR (finalError)                            # M2 give-up
   5. now > global_deadline (never suspended, even during retries)?
        → kill process group, wait/reap → STALLED (hit wall-clock cap)
   6. inside a retry window past retry_deadline (no auto_retry_end)?
        → kill process group, wait/reap → STALLED_RETRY
   7. NOT in a retry window AND (now - last_event_at) > T?
        → kill process group, wait/reap
        → result = STALLED (last event / in-flight context)               # M1/M2
   8. else: keep reading
   ```

4. **Teardown (always)** — ensure the process group is reaped on every exit path
   (success, invalid, crash, stall, round cap); release the lock; leave logs for
   inspection. **`result.json` is always written**, even on a harness-internal
   error (wrap the run so an unexpected exception still emits a `CRASHED` result
   with the traceback) — Claude must never be left polling for a file that never
   appears (the M4 anti-pattern at the harness level).

**Reap semantics (resolves "kill without waiting" vs "must reap"):** never block
waiting for Pi's *natural* exit (M3 means it may never come). But after taking a
kill action, do `SIGTERM` the group → short grace → `SIGKILL` if still alive →
`wait()` to collect status. Always kill the **process group**, not the bare PID,
since Pi may spawn children.

**Artifacts per review** (under a per-run dir): `stdout.raw.log` (every raw stdout
line, tee'd), `events.jsonl` (strict JSONL — valid events plus `malformed_stdout`
records), `stderr.log`, and `result.json` (verdict, items, state, model, cost,
timings, skipped/truncated files).

## Scope, tools, and the verdict contract

- **Default `--no-tools` + curated bundle.** The harness feeds Pi a bounded review
  bundle. Because Pi has no `read`/`grep`/`find`/`ls`, it **cannot independently
  slurp a huge file**, which eliminates M1 at the source. (A size number alone does
  not: with tools, Pi could still open the skipped file.) Since review quality now
  depends entirely on the bundle, the bundle's git contract is explicit:
  - **diffstat** + list of changed paths,
  - **staged diff** and **unstaged diff** (configurable to staged-only),
  - **untracked files** (contents, subject to the size cap),
  - **renamed/deleted** files noted as such,
  - **binary files** noted explicitly (path + status, no content),
  - **generated/build artifacts** skipped explicitly (per ignore rules), listed as skipped,
  - **submodules** summarized (pointer change) or skipped with a caveat,
  - relevant `AGENTS.md`/doc/code excerpts (since `--no-context-files` is set),
  - an explicit **skipped-for-size** list.
  A deterministic-but-incomplete bundle is a review-quality bug, so omissions are
  surfaced, not silent.
- **Whole-bundle cap, not just per-file.** Even with every file under the size cap,
  many changed files can overflow the prompt (context overflow, compaction,
  provider stalls, cost). The harness enforces a per-file *diff* cap
  (`--max-diff-bytes-per-file`) and a total `--max-bundle-bytes`; when it must
  truncate or drop sections it does so by priority (diffs > excerpts), and every
  truncation/omission is recorded in `result.json` and folded into the scoped-clean
  caveat — a `CLEAN` over a truncated bundle is "clean within provided scope."
- **If tools are needed later**, allow only `--tools read,grep,find,ls`, ideally
  with Pi running in a sanitized temp directory containing just the bundle, not the
  real repo.
- **Read-only review prompt** scoped to the changed files; flag only issues
  affecting correctness or stated requirements (avoid nit floods / over-engineering).
- **Verdict contract.** Pi must end its final message with one exact, parseable
  block. **Extraction shape:** find the **last** message in `agent_end.messages[]`
  with `role == "assistant"`; `content` may be an array of blocks, so concatenate
  **only its textual content** (text blocks/strings, skipping tool/thinking/other
  blocks); parse the verdict **only** from that concatenated assistant text — never
  the whole transcript (the echoed bundle contains these very examples) and never
  tool/user content. Within that text, take the **last** line matching
  `^REVIEW: (CLEAN|ISSUES)$`:
  ```text
  REVIEW: CLEAN
  ```
  or:
  ```text
  REVIEW: ISSUES
  1. [Critical] path/file.ext: what is wrong
  2. [Warning] path/file.ext: what is wrong
  ```
  - Allowed severities: **`Critical`**, **`Warning`**, **`Suggestion`**.
  - **Fail closed:**
    - no `^REVIEW: (CLEAN|ISSUES)$` line in the final assistant text → `INVALID`;
    - `REVIEW: ISSUES` with **zero** parseable numbered items → `INVALID`
      (an issues verdict must enumerate at least one item).
- **Scoped clean.** If any file/diff was skipped for size, a `CLEAN` verdict means
  "clean within the provided scope," not absolute clean; the harness records the
  skipped set in `result.json` and Claude surfaces that caveat.
- Because the harness parses the structured `agent_end` message (not a scraped TUI
  pane), the sentinel-echo / prompt-glyph / bracketed-paste failure classes in
  `docs/review-cycle-log.md` do not apply. There is no TUI to drive, no pane to
  scrape.

## Tunable defaults

| Knob | Override | Default | Rationale |
|------|----------|---------|-----------|
| Stall timeout `T` | `--stall-timeout` | 180s since last event (outside retry windows) | gpt-5.5 can pause between events; lower risks false kills. |
| Retry grace | `--retry-grace` | 30s | Slack added to `delayMs` before a retry window counts as `STALLED_RETRY`. |
| Per-review deadline `global_deadline` | `--review-deadline` | 1500s (25m) | Hard wall-clock cap per review; **never suspended**, even during retries. Backstops every timer. |
| File size cap | `--max-file-size` | 256 KB | Larger files are excluded from the bundle + listed as skipped. |
| Per-file diff cap | `--max-diff-bytes-per-file` | 256 KB | A single file's diff is truncated past this; truncation noted. |
| Total bundle cap | `--max-bundle-bytes` | 2 MB | Many sub-cap files can still overflow context / trigger compaction / inflate cost. Past this, lowest-priority sections are dropped. |
| Max rounds `N` | `--max-rounds` | 3 | Then stop and report unresolved items rather than loop forever. |

All are overridable as skill arguments.

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

## Verification results & implementation deltas (post-build)

Built subagent-driven (2026-06-03); 75 stdlib `unittest` tests; live-verified
against real `pi` / gpt-5.5. See `docs/review-cycle-log.md` for the smoke record.
Deltas from the design above, all discovered/confirmed during build + live smoke:

- **`pi --list-models` format (resolved):** it prints a whitespace **table**
  (`provider  model  context …`) to **stderr**, not `provider/model` tokens to
  stdout. `model.resolve_model` parses both the table and the slash form;
  `resolve_from_cli` reads stdout+stderr. Live: resolves `openai-codex/gpt-5.5`.
- **Reviewer instruction (resolved):** the bundle is diff-only, so Pi emits no
  verdict from it alone. The reviewer role + `REVIEW:` contract are passed via
  `--append-system-prompt`. Live: returns a parseable `REVIEW: CLEAN`.
- **Lock identity (delta):** the CLI holds the lock keyed on the **harness PID**
  (the runner owns the Pi process), and reclaim is **fail-closed** — a lock with no
  readable meta is treated as held, never reclaimed.
- **Startup network noise (resolved):** `PI_SKIP_VERSION_CHECK=1` + `PI_TELEMETRY=0`
  set on the subprocess (Pi README); the model call still reaches the provider.
- **M2 confirmed live:** after ~10 rapid `pi` calls the provider blocked, producing
  zero output on both streams; the harness STALLED at the timeout, killed the
  process group, left no orphan, and exited 2 — the watchdog working in the wild.
- **Still open (low risk):** `auto_retry_*` bracketing and the `STALLED_RETRY` path
  are unit-tested (fake events) but not yet observed against a real provider backoff;
  process-group kill/reap verified on macOS via the runner tests + live no-orphan
  checks.
