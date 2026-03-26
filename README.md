# agent-stuff

`agent-stuff` is the public home for reusable assets that support agentic coding workflows.

This repo is intended to hold things like:

- skills for Codex, Claude Code, Pi, and similar agents
- reusable prompt assets and handoff patterns
- shared command snippets and lightweight helper scripts
- documented install conventions for local agent setups

This repo is not the place for:

- secrets
- machine-specific paths
- personal overrides that only make sense on one workstation
- private project context that should stay in a private dotfiles repo

## Recommended Model

Use this repository as the public source of truth for reusable agent assets.

Keep your private chezmoi repo as the machine-specific integration layer that:

- clones or updates this repo
- symlinks or copies the right files into `~/.codex`, `~/.claude`, `~/.pi`, or similar homes
- applies private overrides
- wires in local-only commands, paths, and automation hooks

Recommendation:

1. Publish reusable assets here.
2. Keep agent installation glue in chezmoi.
3. Run a small chezmoi-managed sync script after updates.

That gives you a clean split:

- public repo: reusable content
- private repo: private wiring

## Starter Layout

The initial layout is intentionally small:

- [`codex/`](codex) for Codex-specific assets
- [`claude/`](claude) for Claude Code-specific assets
- [`pi/`](pi) for Pi-specific assets
- [`shared/`](shared) for assets that should be adapted across agents
- [`docs/chezmoi-integration.md`](docs/chezmoi-integration.md) for installation and sync options
- [`docs/migration-plan.md`](docs/migration-plan.md) for the current inventory and move plan
- [`scripts/install-agent-stuff.example.sh`](scripts/install-agent-stuff.example.sh) for a starter sync script pattern

## What Moves Here First

Based on the current chezmoi-managed setup under `~/.local/share/chezmoi`, the first migration candidates are the clearly reusable agent assets:

- Codex skills in `dot_codex/skills/`
- Claude skills in `dot_claude/skills/`
- Claude command prompts in `dot_claude/commands/`
- Pi skills in `dot_pi/agent/skills/`
- shared instructions that can be published without exposing private paths or private project details

The items that should usually stay private or be rewritten before publishing are:

- raw `settings.json` files with personal preferences or local plugin choices
- `AGENTS.md` or `CLAUDE.md` files that mainly describe your private chezmoi workflow
- symlink templates that point at your home directory layout
- project-specific private instructions such as `private_dot_config/emerge/*`

## Migration Strategy

Do not move everything at once. Move by category:

1. Copy the reusable asset into this repo.
2. Remove machine-specific assumptions from the public version.
3. Keep a thin chezmoi wrapper that installs or symlinks it locally.
4. Leave private overrides in chezmoi.

The detailed plan and current inventory are in [`docs/migration-plan.md`](docs/migration-plan.md).

## Integration Options

The realistic integration options are:

- chezmoi externals via `.chezmoiexternal.toml`
- a chezmoi-managed sync script
- a git submodule inside the private dotfiles repo
- direct GitHub install where the agent supports it
- manual clone plus symlink as a simple fallback

The recommended default is documented in [`docs/chezmoi-integration.md`](docs/chezmoi-integration.md).
