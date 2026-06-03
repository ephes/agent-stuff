---
name: pi-review-loop
description: "Use when you want a fresh-context code-review gate before committing — runs Pi (newest GPT model) as a reviewer over the current git diff in a bounded, observable loop, and only proceeds when Pi returns CLEAN. Drives review → fix → re-review up to a round cap. Triggers: \"have pi review this\", \"pi review before commit\", \"run the pi review loop\"."
---

# Pi Review Loop

Run a bounded review cycle: hand the current diff to Pi as a fresh-context reviewer
via the harness, read its structured verdict, and only continue when it is `CLEAN`.
The harness owns Pi's whole lifecycle (spawn, observe, kill/reap), so you never poll
a process or guess whether Pi is stuck — a hung or blocked Pi is detected and killed,
and you always get a structured result.

## When to use

Before committing a change you want reviewed by a different model family. You
implement and fix; Pi reviews with fresh context.

## The loop (you drive this)

1. Make sure the change to review is in the working tree (staged and/or unstaged).
   The harness bundles the diff; you do not paste code.
2. Run one review:

   ```bash
   python3 ~/projects/agent-stuff/claude/skills/pi-review-loop/bin/pi-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/pi-review"
   ```

   It is foreground and returns a structured result — do NOT background it and poll.

3. Interpret by exit code (and read `result.json`):
   - `0` → CLEAN. If it printed `(scoped)`, the bundle skipped/truncated files
     (huge or binary) — treat as "clean within provided scope" and decide whether
     the skipped files matter.
   - `1` → ISSUES. Fix each listed `[Severity] path: message`, then re-run a FRESH
     review (not an edit of the old one).
   - `2` → failed review (INVALID / CRASHED / STALLED / STALLED_RETRY /
     PROVIDER_ERROR). This is NOT a clean review. Inspect `result.json` `error`,
     `stderr.log`, and `events.jsonl`; the usual causes are a transient provider
     stall or an oversized bundle. Fix the cause and re-run. Never treat a failed
     review as a pass.
   - `3` → another review already holds the global lock. Wait or investigate the
     stale lock; do not run concurrent reviews.

4. Stop after at most 3 rounds. If still not CLEAN after 3 rounds, report the
   outstanding items to the user rather than looping forever.

## Hard rules

- A commit-gate "clean" means exit `0` AND you are satisfied any `(scoped)` skips
  are irrelevant. Exit `1`/`2`/`3` are never clean.
- One review at a time — the harness enforces this with a global lock.
- Fix Critical/Warning before re-review; use judgement on Suggestion (avoid
  over-engineering — do not chase every nit).

## Useful flags

`--model <id>` (default: newest GPT auto-resolved), `--review-deadline <s>` (hard
per-review cap, default 1500), `--stall-timeout <s>` (default 180), `--staged-only`,
`--max-bundle-bytes <n>` (default 2MB), `--lock-dir <dir>`.

## Artifacts (in `--run-dir`)

`result.json` (verdict, items, state, model, error, scoped_clean), `events.jsonl`
(strict JSONL event stream), `stdout.raw.log`, `stderr.log`, and `review-bundle.md`
(exactly what Pi reviewed).
