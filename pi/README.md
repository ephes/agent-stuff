# Pi Skills

Skills for the Pi coding agent.

## Skills

| Skill | Purpose |
|-------|---------|
| `commit-ready` | Assess commit readiness without creating a commit |
| `commit-workflow` | Inspect, validate, and commit changes with docs sync |
| `review-handoff` | Generate a code review prompt for a second agent (includes `scripts/gather-changes.sh`) |
| `work-ledger` (shared) | Read and update the work app via its CLI/API, loaded from `../codex/skills/work-ledger` |
| `multi-agent-coordination` (shared) | Coordinator playbook for running many workers, loaded from `../codex/skills/multi-agent-coordination` |

## Install note

Skills with helper scripts (like `review-handoff/scripts/`) must be symlinked
as whole directories, not file-by-file. The chezmoi symlink templates already
handle this correctly.

## What stays private in chezmoi

- `AGENTS.md` — local operating guidance
- `keybindings.json` — personal keybinding preferences
