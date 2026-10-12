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
Never print, copy or commit the token.

On the Studio, run the CLI through the `work` command on PATH
(`~/.local/bin/work`, managed by chezmoi). It loads the env file into its own
process without echoing it, runs `uv run --project ~/projects/work-ledger work`
with your arguments, works from any directory, and exits with a clear error if
the env file, the checkout or `uv` is missing:

```sh
git -C ~/projects/work-ledger pull --ff-only
work items
```

Fallback where the wrapper is not installed: load the env per command in a
subshell, never with `set -x` or `env`/`printenv` in the same command:

```sh
bash -c 'cd ~/projects/work-ledger && set -a && . ~/.config/work/env && set +a && uv run work items'
```

Name yourself so the history reads `api:<token>/<agent>` instead of only the
shared token: `export WORK_AGENT=<name>` (lowercase letters, digits, dashes,
max 40) or `--agent <name>` on any command, which overrides it.

## When to use

- **Read** (`work items`, `work show <slug>`) before choosing, resuming or
  reporting on cross-project work, and when the owner asks what is in flight or
  what waits on them.
  Match repository state with `work items --commit <prefix>` (4-40 hex
  characters, also matches stored abbreviated commits) or
  `work items --branch <name>` (exact branch name); these search the item's
  own fields, not notes, evidence or a request's CI target.
  `work items`, `work notes <slug>` and `work responses` fetch every page, so
  the list is complete; with `--json` the output carries `count`, `truncated`
  and `next_cursor: null`. Treat a stderr warning (`showing N of M`, or a
  server that does not report totals) or `truncated: true` as an incomplete
  read: run it again before concluding that an item or answer does not exist.
- **Update** (`work upsert <slug> ...`) when an item changes stage, owner or
  next action, becomes blocked, or new evidence (commit, receipt, install)
  exists.
- **Note progress** (`work note <slug> "<text>" [--link URL]`) to append to the
  item's history without touching its fields; `work notes <slug>` lists them.
- **Ask** (`work ask <slug> "<text>" --kind question|approval|acceptance`) when
  only the owner can decide or check something.
- **Pick up answers** (`work responses`) at the start of a coordination turn;
  act on each one, then `work consume <id>`.
- **Report usage** (`work usage report --provider claude --window "Weekly ·
  all models" --used <pct> --resets-at <iso> --observed-at now --source
  "claude-desktop get_usage"`; `work usage collect-codex`) for the weekly
  windows only, at session start, when handling results, and at least hourly
  while a campaign runs; stale usage is a coordinator bug.
  Check `work usage status [--max-age 3h] [--provider claude] [--json]`
  before relying on usage numbers: exit 0 means all weekly windows are fresh,
  2 means stale or no weekly readings, and 1 means the call failed. The default
  threshold comes from the server (6 h unless configured); `--max-age` accepts
  hours, minutes, days or seconds. Report fresh readings on exit 2.
- **Report checkouts** with `work checkouts report [--projects-dir DIR]
  [--no-fetch] [--host NAME] [--dry-run]` on the machine holding them. It scans
  direct git checkouts under `$WORK_PROJECTS_DIR` (default `~/projects`),
  fetches remotes and sends one snapshot per host of branches and counts
  (dirty, ahead/behind, unpushed, fetch/scan failures). `--no-fetch` uses the
  last fetch; `--dry-run` prints without sending and needs no token. No file
  names, contents, remote URLs or absolute paths are sent; nothing schedules it.
- Workers inside one project slice do not write to the app; their coordinator
  does, after verifying the report.

## Items

Slug: lowercase words with hyphens. Fields: `title`, `project`, `stage`,
`owner`, `next_action`, `checked_at` (required on every update), optional
`repo_url` (network URL, never a local path), `branch`, `commit`, `worktree`,
`blocked_reason` (required for `blocked`), `notes`, `evidence` (http(s) links;
`--evidence` replaces the list). Fields not given stay unchanged. The `notes`
field is the item's standing summary and `--notes` overwrites it; progress goes
in `work note`.

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
| `accepted` | the owner signed off via an acceptance request or directly in the UI; only the owner can sign off |
| `blocked` / `parked` / `dropped` | cannot move / paused or finished at a checkpoint / abandoned (only the owner reopens it) |

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
- **Owner responses are decisions, not commands to the app.** The app does not merge or deploy. Act on a response in your own session, within the permissions the
  owner gave, record the outcome on the item, then consume the response.
- **Only the owner signs off `accepted`.** For a batch ready for hands-on
  checks, use `work ask <slug> "<what to test>" --kind acceptance --also slug2,slug3`.
  `--also` is repeatable and comma-separated, only for acceptance; API field
  `items`, up to 200 items total including `<slug>`. Requests and responses
  carry `items` (all covered slugs, `<slug>` first) and `accepted_items` (the
  slugs signed off; empty while open, after *problem* or withdrawal).
  The owner's *Tested OK* sets all ticked items in a bulk request to `accepted`
  directly: read `accepted_items`, act on the rest, then consume the response;
  no PUT to `accepted` is needed. Unticked items stay unchanged; fix them and
  ask again. The owner can also accept installed items directly in the UI with
  *Accept selected*. A single-item request keeps the existing flow: wait for
  *tested OK*, then set `--stage accepted`. The API checks the newest
  non-withdrawn acceptance request covering each item; missing, open,
  *problem* or unticked verdicts reject that transition with `400` and
  `details.stage`. Creating an item directly at `accepted` also fails.
  Treat the answer as single-use after a later owner stage decision: if the
  owner moves the item away from `accepted` in the UI or admin (for example,
  reopens it), the old *Tested OK* no longer unlocks `accepted`. The API
  returns `400` with `details.stage` saying to ask again; open a new acceptance
  request and wait for a new answer. An owner-controlled import that changes
  the stage also voids the answer. Re-sending `accepted` for an already
  accepted item is allowed; token stage changes do not void the answer.
- **Only the owner reopens `dropped`.** A token cannot move an item out of
  `dropped` (400). If a dropped item should come back, ask with
  `work ask --kind approval` and wait for the owner to reopen it in the UI; an
  approve answer does not reopen it. Tokens may still drop items and update
  other fields of a dropped item.
- **Avoid lost updates.** Many agents write the same items. Use `work note`
  for progress (notes never conflict and do not change `updated_at`). When
  changing fields an owner or another agent may have edited (`--notes`,
  `--evidence`, `--owner`, `--next-action`), pass the `updated_at` from
  `work show <slug> --json` as `--expect-updated-at <updated_at>`; on a
  conflict (HTTP 409, exit 1) re-read, merge and retry.
- **A failed read is not an empty ledger.** The CLI exits 1 with a one-line
  `work: ...` message when the app cannot be reached or something other than
  the API answers (`unexpected non-JSON response from <base> (HTTP <status>)`:
  a proxy, login or maintenance page). Check `WORK_API_URL` and the app's
  health, retry, and do not write items or report "nothing in flight" from a
  failed command.
- **Never record secrets**: no credentials, tokens, cookies, raw financial or
  résumé data, or raw terminal logs. Summarize and link a receipt instead.

## Worktrees and closeout

- Name a new worktree `ws-<item-slug>` under `~/workspaces` (for example
  `~/workspaces/ws-podcast-main-integration/podcast`) and record that path in the
  item's `worktree` field when you create or claim the item. The field is what
  keeps the checkout out of `workspace-gc`'s removable set while the item is
  active.
- When an item reaches `merged`, `accepted` or `dropped`, the coordinator
  removes that item's worktree (a merge agent removes it itself once the merge
  is verified on the remote). First verify that it is clean and pushed. Then
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
- Record the removal on the item: clear `worktree` (`--worktree ""`) and add
  `work note <slug> "worktree removed <date>"`.
- A weekly report-only job on the Studio writes
  `~/.local/state/workspace-gc/latest.txt` and keeps the item
  `workspace-gc-report` current. It never removes anything. Removing what it
  lists needs the owner's approval and runs `workspace-gc --apply`.

## Example

```sh
work upsert podcast-main-integration \
  --stage merged --commit f26cc99 --next-action "Owner hands-on check" \
  --evidence "Commit=https://github.com/ephes/podcast/commit/f26cc99" --checked-at now
```
