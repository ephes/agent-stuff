# Claude Code Skills and Commands

Skills and command prompts for Claude Code.

## Skills

| Skill | Purpose |
|-------|---------|
| `cross-agent-review-cycle` (shared policy) | Canonical value-driven different-family review loop, loaded from `../codex/skills/cross-agent-review-cycle`; owns continuation, stopping, containment, and commit-gate rules |
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

Claude has no own copy of `cross-agent-review-cycle`; `~/.claude/skills`
symlinks the single agent-neutral copy under `codex/skills/`. That skill in turn
resolves Claude reviews through
`~/projects/agent-stuff/codex/skills/claude-review-loop`. A Claude-only
deployment must install both sibling directories at the same paths; copying only
`claude/skills` is not sufficient for Claude-family review gates.

```text
repository root
  ~/.claude/skills/cross-agent-review-cycle
    -> codex/skills/cross-agent-review-cycle
      -> codex/skills/claude-review-loop
```

## What stays private in chezmoi

- `settings.json` — personal Claude Code configuration
- `CLAUDE.md` — local operating guidance
