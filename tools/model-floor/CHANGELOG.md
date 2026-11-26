# model-floor changelog

## Unreleased

- Exit 2 with the affected path when opening or reading a scan input fails.
  Keep skipping files already absent when a directory scan opens them and
  symlinks that do not resolve, such as loops.
- Reject unreadable, nonregular or invalid UTF-8 allowlists and bound their
  size and glob count before scanning.
- Skip nonregular files without blocking and enforce the 2 MB limit even
  when a file grows during the scan.
- Report failed or timed-out Git enumeration as a scan error. Keep the
  directory walk for targets outside a checkout root.

- Compare long version components without interrupting the scan or losing
  findings later in the input.
- Preserve Git filename bytes when scanning and escape diagnostic paths so
  unusual filenames stay on one output line.
- New tool: `model-floor-check` reports OpenAI model ids below GPT-6.2
  (`gpt-6.1-*`, `gpt-6-*`, `GPT-6 Sol`, `gpt-5*` and older) outside history
  (`CHANGELOG*`, `docs/archive/`, `docs/plans/`, `docs/specs/`,
  `docs/review-cycle-log.md`, `.model-floor-allow` globs, `model-floor: allow`
  line and `model-floor: allow-file` file markers). Its suite runs the check
  over the agent-stuff checkout (owner rule 2026-11-18: no model below 6.2).
