# model-floor changelog

## Unreleased

- Compare long version components without interrupting the scan or losing
  findings later in the input.
- New tool: `model-floor-check` reports OpenAI model ids below GPT-6.2
  (`gpt-6.1-*`, `gpt-6-*`, `GPT-6 Sol`, `gpt-5*` and older) outside history
  (`CHANGELOG*`, `docs/archive/`, `docs/plans/`, `docs/specs/`,
  `docs/review-cycle-log.md`, `.model-floor-allow` globs, `model-floor: allow`
  line and `model-floor: allow-file` file markers). Its suite runs the check
  over the agent-stuff checkout (owner rule 2026-11-18: no model below 6.2).
