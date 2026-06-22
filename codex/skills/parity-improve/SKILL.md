---
name: parity-improve
description: Consume captured pipy parity-loop lessons and materialize each into a gated edit to the skills/docs/tests/harness. Applies only when the working directory is the pipy repo (~/projects/pipy).
---

# Parity Improve (Codex)

This skill applies **only when your working directory is the pipy repo**
(`~/projects/pipy`). If you are anywhere else, do not use it.

Follow the canonical workflow in `docs/parity-loop/improve-body.md` — resolve that
relative path against the pipy repo root and read it now. Consume the open lessons
(`python3 scripts/parity_lessons.py list --status open`) and materialize each into
a gated change; run the steps inline.

Honor the body's hard rules:
- Never self-grade. The different-family review gate is mandatory — since Codex is
  GPT-family, review with `opus-review-loop` (Claude Opus).
- Edits to the workflow's own instructions (`skill-body.md`, `improve-body.md`,
  wrappers) require human or judge-agent sign-off; rejecting a lesson is gated too.
- Never mark a lesson `applied` without a real materializing commit — the helper
  enforces this.
