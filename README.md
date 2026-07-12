# agent-stuff

Public home for reusable coding agent skills, distributed to each agent via
chezmoi symlinks.

## Skill inventory

| Agent | Skill | Purpose |
|-------|-------|---------|
| Codex | `commit-workflow` | Inspect, validate, and commit changes with docs sync |
| Codex | `cross-agent-review-cycle` | Run a bounded different-family review loop; Claude reviews use the supervised local harness |
| Codex | `goal-handoff` | Generate a compact goal condition for another agent session |
| Codex | `implement-handoff` | Generate an implementation prompt for a second agent |
| Codex | `claude-review-loop` | Run the supervised, fail-closed Claude review gate with a configurable model (Opus default) |
| Codex | `review-handoff` | Generate a code review prompt for a second agent |
| Claude | `cross-agent-review-cycle` | Run a bounded different-family review loop; Claude reviews use the supervised local harness |
| Claude | `goal-handoff` | Generate a compact goal condition for another agent session |
| Claude | `handoff-impl` | Generate an implementation prompt for a second agent |
| Claude | `handoff-review` | Generate a code review prompt for a second agent |
| Claude | `pi-review-loop` | Fail-closed Pi gate using only `openai-codex/gpt-5.6-sol` until CLEAN |
| Claude | `mermaid-marked2-markdown` | Create Marked 2-safe Mermaid Markdown for light and dark mode |
| Claude | `claude-review-loop` (shared dependency) | Supervised gate provided by the sibling Codex skill |
| Claude | `summarize-youtube` | Summarize a YouTube video via transcript extraction |
| Claude | `cmsg` (command) | Commit with a clean message, no self-references |
| Pi | `commit-ready` | Assess commit readiness without creating a commit |
| Pi | `commit-workflow` | Inspect, validate, and commit changes with docs sync |
| Pi | `review-handoff` | Generate a code review prompt for a second agent |

## Repo structure

```text
agent-stuff/
  docs/
    review-cycle-log.md
    specs/
    plans/
  codex/
    README.md
    skills/
      commit-workflow/
      cross-agent-review-cycle/
      goal-handoff/
      implement-handoff/
      claude-review-loop/
      opus-review-loop/  # legacy compatibility shim
      review-handoff/
  claude/
    README.md
    skills/
      cross-agent-review-cycle/
      goal-handoff/
      handoff-impl/
      handoff-review/
      pi-review-loop/
      mermaid-marked2-markdown/
      summarize-youtube/
    commands/
      cmsg.md
  pi/
    README.md
    skills/
      commit-ready/
      commit-workflow/
      review-handoff/
  README.md
```

Each agent directory has its own README with agent-specific details (what stays
private, install constraints). Skills may include supporting files beyond
`SKILL.md` — for example, `pi/skills/review-handoff/scripts/gather-changes.sh`.

## How skills get installed

Skills are installed via chezmoi symlinks. The dotfiles repo
(`~/.local/share/chezmoi`) handles two things:

**1. Cloning this repo** via `.chezmoiexternal.toml`:

```toml
["projects/agent-stuff"]
    type = "git-repo"
    url = "git@github.com:ephes/agent-stuff.git"
    refreshPeriod = "168h"
```

This clones the repo on first `chezmoi apply` and pulls updates weekly.
chezmoi processes external entries before deploying managed files, so the
repo is guaranteed to exist before symlinks are created.

**2. Creating symlinks** via templates like:

```
# Example: dot_claude/skills/symlink_handoff-impl.tmpl
{{ .chezmoi.homeDir }}/projects/agent-stuff/claude/skills/handoff-impl
```

Most skills are path-agnostic, and the concrete clone path is normally a
dotfiles-level choice. The shared Claude review workflow is the explicit current
exception: its Codex/Claude skill instructions resolve the authoritative harness
and review log under `~/projects/agent-stuff`. Install this repository at that
path, or update those shared-workflow references together when deploying it
elsewhere.

## Adding or updating a skill

1. Create or edit the skill under the appropriate agent directory
   (e.g., `claude/skills/my-skill/SKILL.md`)
2. If this is a new skill, add a symlink template to the dotfiles repo
   (e.g., `dot_claude/skills/symlink_my-skill.tmpl`)
3. Run `chezmoi apply`
4. Update the agent's README and the skill inventory table above

Similar skills across agents are intentionally kept separate so each version
can be tuned to its agent's model, tool names, and interaction patterns.

## Workflow lessons

Reusable agent/process lessons live in `docs/review-cycle-log.md`. Use it for
things that should improve future skills, goal prompts, tmux orchestration, or
cross-agent review mechanics across projects. Project-specific execution
lessons belong in that project's own docs.

## Design decisions

**Per-agent skills, not shared.** The 10-30% that differs between agents is
prompt engineering tuned to each agent's model and tooling. A shared template
system is not worth the complexity. Revisit if cross-agent duplication becomes
a real maintenance problem.

**Not every agent needs every skill.** Skills exist only where they are useful.
No gap-filling for symmetry.

**Chezmoi symlinks over alternatives.** Chosen over `--add-dir` (Claude Code
only), plugins (overkill for personal use), rsync scripts, and git submodules.
One mechanism across all agents.

**`.chezmoiexternal.toml` for bootstrap.** Declarative, handles both initial
clone and periodic updates, and guarantees ordering (repo exists before
symlinks are created).

## When to revisit this structure

- Substantial duplication across agents causes real maintenance pain
- A new coding agent is added and the per-agent pattern does not scale
- Chezmoi symlinks hit reliability issues
- The Agent Skills spec matures enough for a cross-tool shared format
