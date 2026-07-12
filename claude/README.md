# Claude Code Skills and Commands

Skills and command prompts for Claude Code.

## Skills

| Skill | Purpose |
|-------|---------|
| `cross-agent-review-cycle` | Run a bounded different-family review loop; Claude reviews use `claude-review-loop` |
| `goal-handoff` | Generate a compact goal condition for another agent session |
| `handoff-impl` | Generate an implementation prompt for a second agent |
| `handoff-review` | Generate a code review prompt for a second agent |
| `mermaid-marked2-markdown` | Create Marked 2-safe Mermaid Markdown for light and dark mode |
| `pi-review-loop` | Fail-closed Pi review gate using only `openai-codex/gpt-5.6-sol`; no provider or local-model fallback |
| `claude-review-loop` (shared dependency) | Supervised Claude gate loaded from `../codex/skills/claude-review-loop` |
| `summarize-youtube` | Summarize a YouTube video via transcript extraction |

## Commands

| Command | Purpose |
|---------|---------|
| `cmsg.md` | Commit with a clean message, no self-references |

## Shared review dependency

`cross-agent-review-cycle` resolves Claude reviews through
`~/projects/agent-stuff/codex/skills/claude-review-loop`. A Claude-only deployment
must install that sibling harness at the same path; copying only `claude/skills`
is not sufficient for Claude-family review gates.

```text
repository root
  claude/skills/cross-agent-review-cycle
    -> codex/skills/claude-review-loop
```

## What stays private in chezmoi

- `settings.json` — personal Claude Code configuration
- `CLAUDE.md` — local operating guidance
