# Codex Skills

Skills for the Codex coding agent.

## Skills

| Skill | Purpose |
|-------|---------|
| `commit-workflow` | Inspect, validate, and commit changes with docs sync |
| `cross-agent-review-cycle` | Run a bounded different-family review loop; Claude reviews use `opus-review-loop` |
| `goal-handoff` | Generate a compact goal condition for another agent session |
| `implement-handoff` | Generate an implementation prompt for a second agent |
| `opus-review-loop` | Run the supervised, fail-closed Claude Opus review gate |
| `review-handoff` | Generate a code review prompt for a second agent |

## What stays private in chezmoi

- `AGENTS.md` — local operating guidance for the chezmoi workflow
- `local-dev-orchestration` — depends on local project paths and workstation-specific commands
