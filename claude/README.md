# Claude Code Skills and Commands

Skills and command prompts for Claude Code.

## Skills

| Skill | Purpose |
|-------|---------|
| `cross-agent-review-cycle` (shared policy) | Canonical value-driven different-family review loop, loaded from `../codex/skills/cross-agent-review-cycle`; owns continuation, stopping, containment, and commit-gate rules |
| `goal-handoff` | Generate a compact goal condition for another agent session |
| `handoff-impl` | Generate an implementation prompt for a second agent |
| `handoff-review` | Generate a code review prompt for a second agent |
| `pi-review-loop` | Fail-closed Pi review gate using only `openai-codex/gpt-6-sol` at medium thinking; no provider or local-model fallback. Builds its bundle and slice ledger with the shared modules from `claude-review-loop` |
| `codex-review-loop` | Default reviewer for Claude implementers. Fail-closed Codex review gate using only `gpt-6-sol` at medium reasoning (high on request); no model, provider or reviewer fallback. The reviewer reads only a harness-owned review root, and the model is proven from Codex's session record. Uses the shared bundle, slot pool and slice ledger from `claude-review-loop` |
| `claude-review-loop` (shared dependency) | Supervised Claude gate loaded from `../codex/skills/claude-review-loop` |

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

`pi-review-loop` depends on the same sibling directory: its bundle and ledger
are the shared modules from `claude-review-loop`, imported by relative path, so
the two gates cannot drift apart on redaction, scoping, or round history. It
fails loudly at import rather than falling back to an unredacted bundle.
`codex-review-loop` imports the same modules - bundle, redaction, slot pool and
ledger - the same way.

```text
repository root
  ~/.claude/skills/cross-agent-review-cycle
    -> codex/skills/cross-agent-review-cycle
      -> codex/skills/claude-review-loop
  claude/skills/pi-review-loop
    -> codex/skills/claude-review-loop  (bundle, ledger)
  claude/skills/codex-review-loop
    -> codex/skills/claude-review-loop  (bundle, redaction, lock, ledger)
```

## What stays private in chezmoi

- `settings.json` — personal Claude Code configuration
- `CLAUDE.md` — local operating guidance
