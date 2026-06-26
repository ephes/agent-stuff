---
name: opus-review-loop
description: "Use when Codex needs a fresh-context code-review gate from a different model family before committing - runs Claude Code with the Opus model as a read-only reviewer over the current git diff in a bounded, observable loop, and only proceeds when Opus returns CLEAN. Drives review, fix, and re-review up to a round cap. Triggers: \"have opus review this\", \"claude opus review before commit\", \"run the opus review loop\"."
---

# Opus Review Loop

Run a bounded review cycle: hand the current git worktree delta to Claude Opus as
a fresh-context reviewer via the harness, read its structured verdict, and only
continue when it is `CLEAN`.
The harness owns Claude's whole lifecycle (spawn, observe, kill/reap), so you never poll
a process or guess whether Claude is stuck. A hung or blocked review is detected and killed,
and you always get a structured result.

The harness runs direct `claude -p` with tools disabled and supplies the review
prompt from a prompt file on stdin. It does not use `claude-yolo`; read-only
review does not need write-capable permission bypass. Do not add
`--max-budget-usd`, `--permission-mode`, `--dangerously-skip-permissions`, or
other ad hoc launch flags; the harness owns lifecycle limits and the review
bundle is the entire review surface.
The review must remain a single direct Opus context. Claude Code `Agent`
subagents, Task-style delegation, parallel reviewers, or any other delegated
review are not allowed for this gate.

## When to use

Before committing a change you want reviewed by a different model family. You
implement and fix; Claude Opus reviews with fresh context.

## The loop (you drive this)

1. Make sure the change to review is in the working tree (staged, unstaged, and/or
   untracked). The harness bundles tracked diffs and text untracked files; you do
   not paste code. Read `review-bundle.md` if a scoped result reports skipped or
   truncated files.
2. Run one review:

   ```bash
   python3 ~/projects/agent-stuff/codex/skills/opus-review-loop/bin/opus-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/opus-review"
   ```

   It is foreground and returns a structured result. Do NOT background it and poll.

3. Interpret by exit code (and read `result.json`):
   - `0` -> CLEAN. If it printed `(scoped)`, the bundle skipped/truncated files
     (huge or binary). Treat this as "clean within provided scope" and decide
     whether the skipped files matter. If `events.jsonl`, Claude hook metadata,
     or the transcript shows `Agent` tool use, Task-style delegation,
     `general-purpose` subagents, or parallel reviewer fanout, reject the CLEAN
     result and rerun with delegation disabled or report the review as blocked.
   - `1` -> ISSUES. Fix each listed `[Severity] path: message`, then re-run a FRESH
     review (not an edit of the old one).
   - `2` -> failed review (INVALID / CRASHED / STALLED / STALLED_RETRY /
     PROVIDER_ERROR). This is NOT a clean review. Inspect `result.json` `error`,
     `stderr.log`, and `events.jsonl`; the usual causes are a transient provider
     stall or an oversized bundle. Fix the cause and re-run. Never treat a failed
     review as a pass.
   - `3` -> another review already holds the global lock. Wait or investigate the
     stale lock; do not run concurrent reviews.

4. Stop after at most 3 rounds. If still not CLEAN after 3 rounds, report the
   outstanding items to the user rather than looping forever.

## Timing and Retry Policy

- Keep the default `--stall-timeout` unless there is a concrete reason to shorten
  it. Claude Opus can emit the initial stream event, then stay silent for more
  than 120 seconds before returning a valid review; a too-short override can
  create false `STALLED` results.
- The harness deliberately avoids a positional prompt. `--tools ""` is safe here
  because the prompt is provided on stdin; do not hand-roll
  `claude -p --tools "" "$PROMPT"` without an explicit `--` delimiter.
- If a run exits `2` with `state: STALLED` and `events.jsonl` only contains
  startup/init activity, rerun once with the default or a longer stall timeout
  before declaring the external review unavailable.
- After manually interrupting any review command, check for leftover
  `claude --model opus` processes and terminate the recorded process group before
  starting another review. The harness should reap its own children, but manual
  kills can leave provider calls running.

## Hard rules

- A commit-gate "clean" means exit `0` AND you are satisfied any `(scoped)` skips
  are irrelevant AND the review was direct. Exit `1`/`2`/`3` are never clean.
- Direct review only: no Claude Code `Agent` tool, Task-style delegation,
  subagents, or parallel reviewer fanout. Delegated review output is not a valid
  commit gate even if it says CLEAN.
- One review at a time - the harness enforces this with a global lock.
- Fix Critical/Warning before re-review; use judgement on Suggestion (avoid
  over-engineering - do not chase every nit).

## Useful flags

`--model <id>` (default: `opus`), `--review-deadline <s>` (hard
per-review cap, default 1500), `--stall-timeout <s>` (default 180),
`--retry-grace <s>` (default 30), `--staged-only`, `--max-bundle-bytes <n>`
(default 2MB), `--max-file-size <n>` (default 256KB, untracked files larger are
skipped), `--max-diff-bytes-per-file <n>` (default 256KB, a single file's diff
is truncated past this), `--lock-dir <dir>`.

## Artifacts (in `--run-dir`)

`result.json` (verdict, items, state, model, error, scoped_clean), `events.jsonl`
(strict JSONL event stream), `stdout.raw.log`, `stderr.log`, `review-prompt.txt`,
and `review-bundle.md` (exactly what Opus reviewed).
