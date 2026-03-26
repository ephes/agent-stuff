# Chezmoi Integration

This repo should become the public source of truth for reusable agent assets.

Your private chezmoi repo should remain responsible for:

- where the repo is cloned locally
- which files get installed for each machine
- private overrides
- post-update automation

## Recommended Default

Recommended setup:

1. Clone `agent-stuff` into a stable local path such as `~/src/agent-stuff` or `~/projects/agent-stuff`.
2. Manage that clone from chezmoi.
3. Run a small chezmoi-managed install or sync script after `chezmoi apply`.
4. Keep local overrides and private-only files in the dotfiles repo.

This is the best default because it keeps the public repo clean while preserving your current bootstrap flow.

## Option 1: `chezmoiexternal.toml`

Use chezmoi externals when you want chezmoi to fetch or update the public repo for you.

Example shape:

```toml
[".local/share/agent-stuff"]
type = "git-repo"
url = "git@github.com:jochen/agent-stuff.git"
refreshPeriod = "168h"
```

Why use it:

- keeps clone management inside chezmoi
- works well for machine bootstrap
- simple when the public repo should just exist at a known path

Tradeoffs:

- still needs a second step to install or link files into agent-specific locations
- less explicit than a standalone installer when you want per-agent logic

## Option 2: Chezmoi-Managed Sync Script

This is the recommended option.

Pattern:

1. chezmoi ensures the repo exists locally
2. chezmoi runs a script after apply
3. the script symlinks or copies selected files into agent homes

Example targets:

- `~/.codex/skills/...`
- `~/.claude/skills/...`
- `~/.claude/commands/...`
- `~/.pi/agent/skills/...`

Why this is the default:

- clear separation between public assets and private wiring
- easy to add private overrides after public files are installed
- one place to handle platform-specific path quirks
- easy to evolve as agent install mechanics change

See the starter example at [`scripts/install-agent-stuff.example.sh`](../scripts/install-agent-stuff.example.sh).

## Option 3: Git Submodule In Dotfiles Repo

Use a git submodule if you want the private dotfiles repo to pin an exact public-repo revision.

Why use it:

- strong revision pinning
- explicit update flow

Tradeoffs:

- more friction for normal updates
- more git overhead than most people want for a content repo like this

This is viable, but heavier than necessary for the default workflow.

## Option 4: Direct GitHub Install

Use direct remote install only where the agent officially supports it.

Current working assumption from your setup:

- Codex may support GitHub-based skill installation
- Claude Code and Pi still look like local-install workflows in your current setup

Because that support can change, treat direct GitHub install as agent-specific and optional, not the base architecture for the repo.

When direct install exists, this repo should still remain the public source of truth. Chezmoi can then become optional glue instead of mandatory glue for that agent.

## Option 5: Manual Clone Plus Symlink

This is the simplest fallback.

Pattern:

1. manually clone the repo
2. manually symlink selected files into the agent config directory

Why keep it documented:

- good for testing the repo before automating anything
- good for users who do not use chezmoi

Tradeoffs:

- not reproducible enough for your full personal setup
- easy for links to drift over time

## Recommended Split

Keep these in `agent-stuff`:

- reusable skills
- reusable command prompts
- public examples of install helpers
- agent-specific docs that are safe to publish

Keep these in chezmoi:

- local clone path decisions
- local symlink targets
- private prompts or instructions
- personal settings and plugin choices
- any file that embeds private project paths

## Practical Local Flow

A practical flow for your setup looks like this:

1. `chezmoi apply`
2. chezmoi updates or verifies the local `agent-stuff` clone
3. chezmoi runs a sync script
4. the sync script installs public assets into agent homes
5. chezmoi applies private overlays afterward if needed

That lets the public repo grow independently without collapsing your machine bootstrap into a pile of manual symlinks.
