---
name: pi-review-loop
description: "Use when you want a fresh-context code-review gate before committing — runs Pi only with the approved OpenAI Codex GPT-5.6 Sol model at high reasoning over the current git diff in a bounded, observable loop, and only proceeds when Pi returns CLEAN. Never falls back to Claude/Anthropic, local models, OpenRouter, or another provider. Drives review → fix → re-review up to a round cap. Triggers: \"have pi review this\", \"pi review before commit\", \"run the pi review loop\"."
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
     If the error says `pi unavailable`, the harness could not see a usable GPT
     model from its environment. `pi -p` may still work in another interactive
     shell that has provider auth; verify from the same environment with
     `PI_TELEMETRY=0 pi --list-models gpt` and rerun after auth/model listing
     is visible.
   - `3` → all bounded review slots are busy. Do not report this as a CLEAN
     review and do not claim a review is queued unless you explicitly run a
     separate wait/retry wrapper. Either retry later, inspect stale slot metadata,
     or ask the user whether to raise/lower `--max-concurrent`.

4. Stop after at most 3 rounds. If still not CLEAN after 3 rounds, report the
   outstanding items to the user rather than looping forever.

## Hard rules

- Pi code review uses `openai-codex/gpt-5.6-sol` only. Claude models (Opus,
  Sonnet, Fable, or any other Anthropic model) must run through Claude Code and
  `claude-review-loop`, never through Pi.
- Never use OpenRouter or a local model such as Qwen/Ollama/LM Studio for a
  mandatory code-review gate. If the approved GPT model is unavailable or its
  authentication fails, fail closed and report the blocker; do not substitute
  another model, provider, or transport.
- A commit-gate "clean" means exit `0` AND you are satisfied any `(scoped)` skips
  are irrelevant. Exit `1`/`2`/`3` are never clean.
- Bounded parallelism only — the harness enforces a per-user slot pool. It now
  defaults to 3 concurrent Pi reviews to avoid a cross-repo bottleneck while still
  limiting provider pressure. Set `PI_REVIEW_MAX_CONCURRENT=1` or pass
  `--max-concurrent 1` if provider stalls return.
- A `CLEAN` result over an empty worktree is invalid: the harness refuses to run
  the reviewer when there are no staged, unstaged, or untracked changes.
- Fix Critical/Warning before re-review; use judgement on Suggestion (avoid
  over-engineering — do not chase every nit).

## Useful flags

`--model <id>` exists for explicitness but accepts only
`openai-codex/gpt-5.6-sol`; any other value fails before Pi starts. When omitted,
the harness requires that same model to appear in Pi's authenticated listing.
Pi runs at `high` reasoning. `--review-deadline <s>` (hard
per-review cap, default 1500), `--stall-timeout <s>` (default 180), `--staged-only`,
`--max-bundle-bytes <n>` (default 2MB), `--max-file-size <n>` (default 256KB, untracked
files larger are skipped), `--max-diff-bytes-per-file <n>` (default 256KB, a single
file's diff is truncated past this), `--lock-dir <dir>` (slot-pool directory),
`--max-concurrent <n>` (default 3, or `PI_REVIEW_MAX_CONCURRENT`).

## Artifacts (in `--run-dir`)

`result.json` (verdict, items, state, model, error, scoped_clean), `events.jsonl`
(strict JSONL event stream), `stdout.raw.log`, `stderr.log`, and `review-bundle.md`
(exactly what Pi reviewed).
