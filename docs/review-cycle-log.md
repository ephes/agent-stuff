# Review Cycle And Agent Workflow Log

Status: active log

This log captures reusable agent/process lessons from goals, review cycles,
tmux orchestration, skill behavior, validation workflows, and model pairing.
Keep entries summary-safe: record what was expected, what happened instead,
impact, fix or follow-up, and status. Do not include raw prompts, transcripts,
secrets, credentials, or large tool output.

Project-specific execution lessons belong in the project repo, not here.

## Entry Template

```md
## YYYY-MM-DD - Short Title

- Repo:
- Goal or slice:
- Implementer:
- Reviewer:
- Expected:
- Actual:
- Impact:
- Fix or follow-up:
- Status:
```

## 2026-05-28 - Multi-Line Prompts Need Bracketed Paste

- Repo: podcast / agent-stuff.
- Goal or slice: cross-agent review cycle skill.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: a multi-line review prompt could be delivered to a detached
  reviewer TUI with `tmux send-keys -l`.
- Actual: embedded newlines can submit partial prompts, and keys can arrive
  before the reviewer TUI is ready.
- Impact: the reviewer may receive a truncated or empty task, making a review
  cycle appear complete without a meaningful review.
- Fix or follow-up: write the prompt to a temp file, load it into a tmux
  buffer, paste with bracketed paste, and wait for a visible ready state before
  pasting.
- Status: fixed in `cross-agent-review-cycle`.

## 2026-05-28 - Completion Sentinels Must Avoid Prompt Echo

- Repo: podcast / agent-stuff.
- Goal or slice: cross-agent review cycle skill.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: polling for `=== REVIEW COMPLETE ===` would detect when the
  reviewer finished.
- Actual: the prompt itself contained the literal sentinel, so pane capture
  could match the echoed prompt and stop before the reviewer responded.
- Impact: the driver could parse an incomplete pane as a finished review.
- Fix or follow-up: require at least two sentinel matches, fail closed if the
  second match never appears, and avoid printing repeated full captures while
  polling. When quoting prior review reports, strip their trailing sentinel so
  quoted history cannot supply the second match.
- Status: fixed in `cross-agent-review-cycle`.
