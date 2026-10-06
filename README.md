# agent-stuff

Public home for reusable coding agent skills, distributed to each agent via
chezmoi symlinks.

## Skill inventory

| Agent | Skill | Purpose |
|-------|-------|---------|
| Codex | `commit-workflow` | Inspect, validate, and commit changes with docs sync |
| Codex, Claude | `cross-agent-review-cycle` | Canonical value-driven different-family review loop; owns the continuation, stopping, containment, and commit-gate rules. One shared copy under `codex/skills/`, symlinked for both agents |
| Codex, Claude, Pi | `work-ledger` | How coordinators read and update the work app through its `work` CLI/API (on the Studio via the chezmoi-managed `work` command, which loads the token without echoing it) (stage ladder, verify-before-write, progress notes, agent attribution and the lost-update guard, owner requests and responses, usage reports). Agent-neutral like `cross-agent-review-cycle`: one copy under `codex/skills/`, symlinked for every agent |
| Codex, Claude, Pi | `multi-agent-coordination` | How a coordinator runs many workers: roles (coordinator, clerk, scouts), worker brief checklist, quota pacing, owner-load reduction, infrastructure and cleanup safety. Agent-neutral; one copy under `codex/skills/`, symlinked for every agent |
| Codex | `goal-handoff` | Generate a compact goal condition for another agent session |
| Codex | `implement-handoff` | Generate an implementation prompt for a second agent |
| Codex | `claude-review-loop` | Run the supervised, fail-closed Claude review gate with a configurable model (Opus 5.5 at medium effort by default), working in a sandboxed throwaway copy of the repository; default reviewer for Codex and Pi implementers |
| Codex | `review-handoff` | Generate a code review prompt for a second agent |
| Claude | `goal-handoff` | Generate a compact goal condition for another agent session |
| Claude | `handoff-impl` | Generate an implementation prompt for a second agent |
| Claude | `handoff-review` | Generate a code review prompt for a second agent |
| Claude | `pi-review-loop` | Fail-closed Pi gate using only `openai-codex/gpt-6.1-sol` at medium thinking (high on request), working in an unsandboxed throwaway copy of the repository; shares the bundle and slice ledger with `claude-review-loop` |
| Claude | `codex-review-loop` | Default reviewer for Claude implementers: fail-closed Codex gate using only `gpt-6.1-sol` at high reasoning (medium on request, `--effort medium`); proves the model from Codex's session record, confines the reviewer to a sandboxed throwaway copy of the repository, and shares the bundle, slot pool and slice ledger with `claude-review-loop` |
| Claude | `claude-review-loop` (shared dependency) | Supervised gate provided by the sibling Codex skill |
| Claude | `cmsg` (command) | Commit with a clean message, no self-references |
| Pi | `commit-ready` | Assess commit readiness without creating a commit |
| Pi | `commit-workflow` | Inspect, validate, and commit changes with docs sync |
| Pi | `review-handoff` | Generate a code review prompt for a second agent |

## Tools

| Tool | Purpose |
|------|---------|
| [`tools/workspace-gc`](tools/workspace-gc/README.md) | Live inventory of agent checkouts under `~/workspaces` (classes A removable / B after push / C needs owner / D keep), guarded removal of class A only (dry run by default), and the report behind the weekly Studio job. The `work-ledger` closeout step uses its single-path `remove` |

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on pushes to `main` and on
pull requests, with no secrets:

- the hermetic unittest suites of `claude-review-loop`, `codex-review-loop`,
  `pi-review-loop` and `tools/workspace-gc`, on a macOS runner because the
  harnesses target the Studio. The live model canaries stay skipped: never set
  `CODEX_REVIEW_RUN_CANARY` or `CLAUDE_REVIEW_RUN_CLAUDE_CANARY` in CI.
- `.github/scripts/check_skill_frontmatter.py`: every `*/skills/*/SKILL.md`
  has YAML frontmatter whose `name` matches its directory and a non-empty
  `description` (needs PyYAML).

Run a suite locally the same way, e.g.
`cd tools/workspace-gc && python3 -m unittest discover -s tests -t .` (the
skill suites use `discover -s tests` from the skill directory).

## Repo structure

```text
agent-stuff/
  .github/              # CI workflow and its frontmatter check
  docs/
    review-cycle-log.md
    archive/            # closed log history
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
      work-ledger/       # shared by Codex, Claude and Pi
      multi-agent-coordination/  # shared by Codex, Claude and Pi
  claude/
    README.md
    skills/
      goal-handoff/
      handoff-impl/
      handoff-review/
      pi-review-loop/
      codex-review-loop/
    commands/
      cmsg.md
  pi/
    README.md
    skills/
      commit-ready/
      commit-workflow/
      review-handoff/
  tools/
    workspace-gc/       # agent-neutral CLI, not a skill; run from this checkout
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
can be tuned to its agent's model, tool names, and interaction patterns. The
exception is `cross-agent-review-cycle`: it is agent-neutral policy, and keeping
two copies let them drift into contradictory stopping rules, so every agent
symlinks the single copy under `codex/skills/`. `work-ledger` follows the same
rule: it describes a shared data contract, not agent mechanics, and so does
`multi-agent-coordination`, which is coordination policy.

## Handoff review consistency

Implementation and review handoffs carry the canonical value-driven stopping
policy, cumulative finding dispositions, and scoped repair context into fresh
sessions. Implementation-only workers leave review to the independent driver;
explicit end-to-end ownership permits installed review harnesses. Advisory
closure is reported as advisory, and failed attempts never count as reviews.
Synthetic behavioral forward checks are in
[docs/fixtures/handoff-review/requests.md](docs/fixtures/handoff-review/requests.md).

The canonical policy, handoffs and `pi-review-loop` all require Pi
`openai-codex/gpt-6.1-sol`, the model pinned for both review harnesses on
2026-09-30. A required Pi gate needs Pi's OpenAI Codex subscription login; when
that login or the model is unavailable the gate is blocked, without a
model/provider substitution. The implementer tier keeps `gpt-6-sol`.

## Workflow lessons

Reusable agent/process lessons live in `docs/review-cycle-log.md`. Use it for
things that should improve future skills, goal prompts, tmux orchestration, or
cross-agent review mechanics across projects. Project-specific execution
lessons belong in that project's own docs, and per-run metrics belong nowhere.

Every entry ends with a `Promotion:` line naming the skill and section that now
carries the rule, or `pending` with what is still missing. Promoting the lesson
is part of closing the cycle, not a later cleanup pass:
`grep '^- Promotion: pending' docs/review-cycle-log.md` is the backlog.

Append the lesson and commit+push it immediately in its own small commit
(fetch/rebase first); never leave the log uncommitted.

Closed history lives in `docs/archive/`.

## Design decisions

**Per-agent skills, not shared — except shared policy.** The 10-30% that
differs between agents is prompt engineering tuned to each agent's model and
tooling. A shared template system is not worth the complexity. But a skill that
encodes gate policy rather than agent mechanics gets exactly one copy that every
agent symlinks: duplicating `cross-agent-review-cycle` produced a Claude copy
with a hard three-cycle cap and a Codex copy with value-driven stopping, and the
review loop's behavior then depended on which file the session happened to load.

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
