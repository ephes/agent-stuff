# Migration Plan

This document captures the current agent-related assets found in the private chezmoi source at `~/.local/share/chezmoi` and proposes how to move the reusable parts into this public repo.

## Current Inventory

### Codex

Current chezmoi-managed items:

- `dot_codex/AGENTS.md`
- `dot_codex/skills/commit-workflow/symlink_SKILL.md.tmpl`
- `dot_codex/skills/implement-handoff/symlink_SKILL.md.tmpl`
- `dot_codex/skills/local-dev-orchestration/SKILL.md`
- `dot_codex/skills/review-handoff/symlink_SKILL.md.tmpl`

Recommendation:

- move the reusable skills into [`codex/skills/`](../codex/skills)
- do not publish the current `dot_codex/AGENTS.md` as-is because it mostly documents your private chezmoi workflow
- replace private installation instructions with a public repo-level install story
- current public migration status:
  - migrated: `commit-workflow`, `implement-handoff`, `review-handoff`
  - still private: `local-dev-orchestration`
  - chezmoi now links the migrated `SKILL.md` files back to this public repo

### Claude Code

Current chezmoi-managed items:

- `dot_claude/CLAUDE.md`
- `dot_claude/commands/symlink_cmsg.md.tmpl`
- `dot_claude/settings.json`
- `dot_claude/skills/symlink_handoff-impl.tmpl`
- `dot_claude/skills/symlink_handoff-review.tmpl`
- `dot_claude/skills/summarize-youtube/SKILL.md`

Recommendation:

- move reusable skills into [`claude/skills/`](../claude/skills)
- move reusable command prompts into [`claude/commands/`](../claude/commands)
- treat `settings.json` as private by default unless you want to publish an intentionally curated example version
- do not publish `dot_claude/CLAUDE.md` unchanged because it is mostly local operating guidance
- current public migration status:
  - migrated: `skills/handoff-impl`, `skills/handoff-review`, `commands/cmsg.md`
  - still private: `skills/summarize-youtube`, `settings.json`, `CLAUDE.md`
  - chezmoi now links the migrated Claude assets back to this public repo

### Pi

Current chezmoi-managed items:

- `dot_pi/agent/AGENTS.md`
- `dot_pi/agent/keybindings.json`
- `dot_pi/agent/skills/symlink_commit-ready.tmpl`
- `dot_pi/agent/skills/symlink_commit-workflow.tmpl`
- `dot_pi/agent/skills/symlink_review-handoff.tmpl`

Recommendation:

- move reusable skills into [`pi/skills/`](../pi/skills)
- keep `keybindings.json` private unless you explicitly want to publish your preferred defaults
- do not publish `dot_pi/agent/AGENTS.md` unchanged because it is mostly about local chezmoi management
- move whole skill directories when a skill includes helper scripts, not just `SKILL.md`
- current public migration status:
  - migrated: `commit-ready`, `commit-workflow`, `review-handoff`
  - still private: `AGENTS.md`, `keybindings.json`
  - chezmoi now links the migrated Pi skill directories back to this public repo so the installed `~/.pi/agent/skills/...` layout resolves through directory symlinks

### Private Project Glue

Current chezmoi-managed items with strong private or machine-specific coupling:

- `private_dot_config/emerge/AGENTS.md`
- `private_dot_config/emerge/CLAUDE.md`
- `private_dot_config/emerge/skills/implement-handoff/SKILL.md`
- `private_dot_config/emerge/skills/review-handoff/SKILL.md`
- `private_dot_config/emerge/skills/review-handoff/scripts/executable_gather-changes.sh`
- `private_dot_config/emerge/skills/symlink_commit-ready.tmpl`
- `private_dot_config/emerge/skills/symlink_commit-workflow.tmpl`
- `private_dot_config/emerge/Justfile`
- `private_dot_config/emerge/lib-workspace.sh`
- `private_dot_config/emerge/symlink_keybindings.json.tmpl`
- `private_dot_config/emerge/symlink_settings.json.tmpl`

Recommendation:

- keep project-specific private instructions in chezmoi
- only extract patterns that are reusable across projects
- do not move symlink templates into this public repo except as generic examples
- treat helper scripts and project automation files as reviewed private glue unless they are intentionally generalized for publication

## What To Move First

First migration batch:

1. Codex skills that do not depend on private project paths
2. Claude skills and command prompts that are generally reusable
3. Pi skills that are generally reusable

Second migration batch:

1. sanitized example config files for Claude or Pi, if you want public examples
2. shared prompts or templates that exist in more than one agent flavor
3. generic helper scripts that install or sync assets locally

Leave private for now:

- raw personal settings
- project-local instructions
- path-templated symlink files
- anything that exposes private repositories or local paths

## Target Layout

Proposed long-term layout:

```text
agent-stuff/
  codex/
    skills/
  claude/
    skills/
    commands/
  pi/
    skills/
  shared/
    prompts/
    templates/
    scripts/
  docs/
  scripts/
```

## Migration Method

For each asset:

1. copy the current chezmoi-managed version into this repo
2. remove private path assumptions and workstation-only details
3. add public-facing docs if the asset needs install context
4. switch chezmoi to install the public version
5. keep private overlays only where genuinely needed

## Working Mapping

The most likely near-term mapping is:

- `~/.local/share/chezmoi/dot_codex/skills/*` -> [`codex/skills/`](../codex/skills)
- `~/.local/share/chezmoi/dot_claude/skills/*` -> [`claude/skills/`](../claude/skills)
- `~/.local/share/chezmoi/dot_claude/commands/*` -> [`claude/commands/`](../claude/commands)
- `~/.local/share/chezmoi/dot_pi/agent/skills/*` -> [`pi/skills/`](../pi/skills)

## Open Questions

- Whether you want to publish example `settings.json` or `keybindings.json` files at all
- Whether Codex remote GitHub skill install should become a first-class documented path once you confirm the exact supported format
- Whether the agent-specific handoff skills should stay duplicated per agent or be factored into shared source templates with generated variants
