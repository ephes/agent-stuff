---
name: work-ledger
description: Use when coordinating multi-project agent work through the owner's work app (https://work.home.xn--wersdrfer-47a.de, repo github.com/ephes/work-ledger) - reading what is in flight or waiting on the owner, recording a stage change, asking the owner something, picking up the owner's answers, or reporting subscription usage. Provider-neutral; shared by Claude, Codex and Pi coordinators.
---

# Work Ledger

The work app at `https://work.home.xn--wersdrfer-47a.de` is the source of truth
for multi-project agent work. Chat history, worker reports and old dashboards
are not. Coordinators use it through the `work` CLI in `~/projects/work-ledger`
(a thin client for the token API under `/api/`). The repository `README.md`
documents the API; this skill is the working summary.

The YAML files in `ledger/items/` are frozen history (imported once); do not
edit them. `receipts/` holds campaign receipts that evidence links point to.

## Setup

The shared `coordinator` token and URL live in `~/.config/work/env` (mode 600).
Never print, copy or commit the token. Load it into the environment per command:

```sh
cd ~/projects/work-ledger && git pull --ff-only
bash -c 'set -a && . ~/.config/work/env && set +a && uv run work items'
```

## When to use

- **Read** (`work items`, `work show <slug>`) before choosing, resuming or
  reporting on cross-project work, and when the owner asks what is in flight or
  what waits on them.
- **Update** (`work upsert <slug> ...`) when an item changes stage, owner or
  next action, becomes blocked, or new evidence (commit, receipt, install)
  exists.
- **Ask** (`work ask <slug> "<text>" --kind question|approval|acceptance`) when
  only the owner can decide or check something.
- **Pick up answers** (`work responses`) at the start of a coordination turn;
  act on each one, then `work consume <id>`.
- **Report usage** (`work usage report ...`, `work usage collect-codex`) when
  checking in; readings a few hours old are fine.
- Workers inside one project slice do not write to the app; their coordinator
  does, after verifying the report.

## Items

Slug: lowercase words with hyphens. Fields: `title`, `project`, `stage`,
`owner`, `next_action`, `checked_at` (required on every update), optional
`repo_url` (network URL, never a local path), `branch`, `commit`, `worktree`,
`blocked_reason` (required for `blocked`), `notes`, `evidence` (http(s) links;
`--evidence` replaces the list). Fields not given stay unchanged.

`owner` is who acts next: `claude`, `codex`, `herdr:<workspace label>`,
`jochen`.

## Stage ladder

Each stage is a distinct claim. Never write "done"; pick the strongest stage you
verified, not the one you expect.

| Stage | Verified by |
|-------|-------------|
| `idea` | noted only |
| `designed` | an accepted design or plan exists |
| `prototype` | throwaway or synthetic exploration exists, not production code |
| `implementing` | production work under way |
| `reviewed` | an independent review gate passed |
| `local` | commit exists only in a local checkout |
| `pushed` | `git ls-remote` shows the commit on a non-default branch |
| `merged` | the commit is on the remote default branch |
| `installed` | running on the target device or host (version observed there) |
| `accepted` | the owner checked it hands-on and said yes |
| `blocked` / `parked` / `dropped` | cannot move / paused or finished at a checkpoint / abandoned |

Reviewed is not merged, merged is not installed, installed is not accepted.
Items with history cannot be deleted; retire them as `dropped`.

## Rules

- **Verify before writing.** Check git (`git ls-remote`, `merge-base
  --is-ancestor`, `status`), herdr, CI or device state yourself. Worker reports
  and receipts are claims; record what you observed, and say in `notes` what
  you could not verify.
- **`checked_at` is when the facts were checked** (`--checked-at now` only if
  you just re-verified them), not when you edited the item.
- **Owner requests** are one concrete, answerable question each
  (`Merge f26cc99 into main?`). Check `work show <slug>` first and do not
  re-ask something already open or answered; withdraw requests that became
  moot (`work withdraw <id>`).
- **Owner responses are decisions, not commands to the app.** The app executes
  nothing. Act on a response in your own session, within the permissions the
  owner gave, record the outcome on the item, then consume the response.
- **Never record secrets**: no credentials, tokens, cookies, raw financial or
  résumé data, or raw terminal logs. Summarize and link a receipt instead.

## Worktrees and closeout

- Name a new worktree `ws-<item-slug>` under `~/workspaces` (for example
  `~/workspaces/ws-podcast-main-integration/podcast`) and record that path in the
  item's `worktree` field when you create or claim the item. The field is what
  keeps the checkout out of `workspace-gc`'s removable set while the item is
  active.
- When an item reaches `merged`, `accepted` or `dropped`, the coordinator
  removes that item's worktree. First verify that it is clean and pushed. Then
  run the guarded single-path removal, which refuses anything that is not class
  A (removable):

  ```sh
  ~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc remove <path>          # dry run: class and reasons
  ~/projects/agent-stuff/tools/workspace-gc/bin/workspace-gc remove --apply <path>
  ```

  `git worktree remove <path>` without `--force` is the fallback. Never use
  `--force` and never `rm -rf` a checkout. If removal is refused (dirty,
  unpushed, stash, device backups, in use), leave the checkout and say why in
  the item's `notes`, or ask the owner.
- Record the removal on the item: clear `worktree` (`--worktree ""`) and note
  `worktree removed <date>` in `notes`.
- A weekly report-only job on the Studio writes
  `~/.local/state/workspace-gc/latest.txt` and keeps the item
  `workspace-gc-report` current. It never removes anything. Removing what it
  lists needs the owner's approval and runs `workspace-gc --apply`.

## Example

```sh
bash -c 'set -a && . ~/.config/work/env && set +a && uv run work upsert podcast-main-integration \
  --stage merged --commit f26cc99 --next-action "Owner hands-on check" \
  --evidence "Commit=https://github.com/ephes/podcast/commit/f26cc99" --checked-at now'
```
