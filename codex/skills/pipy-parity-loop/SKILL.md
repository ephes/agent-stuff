---
name: pipy-parity-loop
description: Drive one pi-mono parity gap end to end in the pipy repo (select gap, plan, different-family review, implement, docs, review until CLEAN, commit). Applies only when the working directory is the pipy repo (~/projects/pipy).
---

# Pipy Parity Loop (Codex)

This skill applies **only when your working directory is the pipy repo**
(`~/projects/pipy`). If you are anywhere else, do not use it.

Follow the canonical workflow in `docs/parity-loop/skill-body.md` — resolve that
relative path against the pipy repo root and read it now. Drive exactly **one**
parity gap end to end; run the phases inline.

Honor the body's hard rules:
- Never self-grade. The different-family review gate is mandatory — since Codex
  is GPT-family, review with `claude-review-loop` (Opus by default, or the
  explicitly configured Claude model).
- Operator override is a stop/escalation, never a pass.
- Work on trunk (`main`); never weaken or delete tests to pass a gate.

The body's Phase 0 also drains the lesson backlog and Phase 9 captures lessons via
`scripts/parity_lessons.py`; to apply accumulated lessons use the
`parity-improve` skill.
