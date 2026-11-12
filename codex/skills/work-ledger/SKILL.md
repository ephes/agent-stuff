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
- **Check rejections** (`work rejected --search "<words>" [--project P]
  [--json]`) before creating an item or proposing work: the owner's *Not
  wanted* decisions, with date and reason (rule under **Planning and picking
  work**).
- **Update** (`work upsert <slug> ...`) when an item changes stage, owner or
  next action, becomes blocked, or new evidence (commit, receipt, install)
  exists.
- **Note progress** (`work note <slug> "<text>" [--link URL]`) to append to the
  item's history without touching its fields; `work notes <slug>` lists them.
- **Ask** (`work ask <slug> "<text>" --kind question|approval|acceptance`)
  rarely: only for C-class decisions and subjective acceptance checks
  (`multi-agent-coordination`, **Decision classes**). Unknown means
  investigate or park, not ask.
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

Slug: lowercase words with hyphens. Fields: `title`, `summary`, `decision`,
`project`, `stage`, `owner`, `next_action`, `checked_at` (required on every update), optional
`repo_url` (network URL, never a local path), `branch`, `commit`, `worktree`,
`blocked_reason` (required for `blocked`), `notes`, `evidence` (http(s) links;
`--evidence` replaces the list). Fields not given stay unchanged. The `notes`
field is the item's standing summary and `--notes` overwrites it; progress goes
in `work note`.

**Always set `summary` when creating an item** (`--summary`, at most 600
characters), and keep it true when the item changes materially: 1–3 plain
German sentences for the owner saying what the problem or change is, what will
happen (or happened), and the benefit. No file paths, slice ids, line numbers
or internal jargon. The owner decides from the tile; a title like "Codex:
archive slices from scout round 75" tells them nothing. Example:
`--summary "Im Archiv kann ein veralteter Admin-Stand neuere Transkripte
überschreiben. Es kommt eine Prüfung dazu, die das verhindert. Nutzen: keine
stillen Datenverluste."` Set `--decision "<one plain German question>"` (at
most 300 characters) only while the owner really has something to decide about
the item, e.g. "Soll m4a in Delve unterstützt werden, oder reicht mp3?"; clear
it with `--decision ""` once answered. Both show on the owner's tiles; the
decision is highlighted. A decision does not replace `work ask` for C-class
questions: ask, and mirror the question in `--decision`.

`owner` is who acts next: `claude`, `codex`, `herdr:<workspace label>`,
`jochen`.

## Planning and picking work

Rollout: `/plan/`, `work next`, `work plan` and the `--horizon`/`--topics`/
`--expedite` upsert flags are live since 2026-11-08: the work app is deployed
and `work plan` returns horizons. The one-off queue import has run; the
former codex-q queue items sit in Next. Read and dispatch from `work next`/
`work plan`; queue files are only generated copies (below), and the import is
not rerun.

Campaign rollout: the separate work-ledger campaign deploy (migration 0021,
merged 2026-11-09, deployed by the owner afterwards) adds the `campaign` field
and moves `codex-burn` out of the codex-q items' topics into their campaign.
Check with `work show <slug> --json`: a `campaign` key means it is live. Before
that deploy upsert answers 400 "Unknown fields" for `--campaign`, and the old
server silently ignores `?campaign=` (the CLI notices and `items`/`plan`/`next
--campaign` exit 1; a direct API read would return unfiltered items). The
codex-q items still carry topic `codex-burn` until then: leave new items
without a campaign, never add `codex-burn` as a topic, and read the existing
ones with `--topic codex-burn`.
After the deploy use `--campaign codex-burn` only.

The owner prioritizes on `/plan/`: Now / Next / Later with a rank order inside
each horizon (↑ ↓ ⤒ and → Now/Next/Later buttons), an inbox of unplanned
`idea`/`designed` items, and free topic slugs shown on each card. Stage still describes
execution progress; horizon describes the owner's plan.

- Read `work plan` for the ordered plan, or `work plan --json` for structured
  data. The plan includes Now, Next, Later and Unplanned, with `--project P`,
  `--topic T` and `--campaign C` filters. Use
  `work next [--project P] [--topic T] [--campaign C] [--limit N]` to read available
  work from **Now**, in the same rank order: stage `designed` or `prototype`,
  no open owner request (including bulk acceptance), and owner exactly
  `jochen`, `claude`, `codex` or `pi` (the owner/coordinator pool identities).
  Named workers such as `herdr:<workspace>` and unknown owners are excluded;
  there is no live worker registry, so verify availability before dispatch.
  Blocked and parked items are excluded. `--limit` is positive, defaults to 1,
  and applies after filtering across all pages. `--json` includes the returned
  `count` and pre-limit `available_count`. Incomplete reads fail instead of
  appearing as an empty ready queue. The Now WIP warning above six items is a hint;
  `work next` still returns available work.
- A read does not claim an item. Re-read before dispatch, check that no worker
  already owns it, then claim with `--stage implementing --owner <worker>`
  and `--expect-updated-at` from `work show <slug> --json`.
- Agents create new items only at the **end of Next or Later**:
  `work upsert <slug> --title "..." --summary "..." --project P --stage idea
  --horizon next --topics security,infra --checked-at now`. Omit rank and neighbours; the
  server appends. `--topics` supplies at most five slug-validated free topics
  (no Topic table); `--topics ""` clears the list. Omitted fields stay unchanged.
  Reuse topic slugs already shown by `work plan` where they fit. Topics name
  themes (`infra`, `podcast`), never a campaign, queue or source: mark those
  with `--campaign <slug>` (one slug, e.g. `--campaign codex-burn` for Codex
  burn-down work; `--campaign ""` clears it) and list them with
  `work items --campaign <slug>`. Never write `--topics codex-burn`.
- **Check the owner's rejections first.** Before creating an item or proposing
  work, run `work rejected --search "<key words of the title>"` (add
  `--project P` to narrow it). The owner marks unwanted ideas *Not wanted* in the
  app; a match means he already said no. Do not re-propose it unless something
  materially changed, and then say in the item's notes what changed since the
  rejection (date and reason are in the listing). `work upsert` also warns on
  stderr (`previously_rejected` in the API answer) when an item matches a
  rejection; the write has already happened, so act on it: if nothing material
  changed, retire a new item with `--stage dropped` and a `work note` naming
  the matched rejection; otherwise record what changed in its notes (`--notes`
  overwrites the summary, so use `--expect-updated-at` on an existing item).
  Only the owner rejects; tokens can only read rejections.
- **Agents never reorder existing items or move items into Now**, including
  within Next. Routine stage/owner updates omit horizon and rank. Raise any
  reorder or horizon-change proposal in the weekly chat check for the owner to
  apply, not as a separate request. An approval response alone does not authorize an
  agent to perform the move. Expedite is a boolean flag with at most one
  item; it does not grant permission to change order or horizon.
  `--expedite` / `--no-expedite` express booleans, but the token API rejects
  changes to this owner-only flag. Expedite does not override rank order.
- At each quota reset and at the weekly planning check, present Next
  candidates with context to the owner in chat. The owner chooses what moves
  into Now and its order. The app needs no reprioritization schedule.
- After the coordinator's one-off import, queue files are generated read-only
  copies: `work plan --format queue > queue.txt` (or `QUEUE.md`). Never edit
  those copies to prioritize, and never dispatch from an old file instead of
  reading `work next`. The coordinator runs `manage.py import_plan_queues`
  after deployment with an explicit JSON mapping for Atlas prose (and any
  Codex legacy label overrides). It previews by default; `--apply` appends
  existing unplanned items to Next atomically, Codex then Atlas, deduplicating
  at first occurrence; `--campaign codex-burn` also tags the Codex-queue items
  with that campaign. Missing/unmapped/already planned items abort. It keeps
  stages and checked times, including completed entries; it never creates
  items or promotes them to Now. See the work-ledger README for mapping and
  database setup. Workers never run it.

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
- **Owner requests** are only C-class decisions (`multi-agent-coordination`,
  **Decision classes**) and subjective acceptance checks (below): merges,
  routine deploys, parked reviews and planning proposals are never asked. Each request is one plain-language sentence saying what changes for
  the owner, plus a recommendation and the safe default if he does not answer
  (`Retire the Minecraft server? Nobody has played since June. I recommend
  retiring it; without an answer it keeps running.`). One decision per
  request, never bundled with others or hidden in notes. Check `work show
  <slug>` first and do not re-ask something already open or answered;
  withdraw requests that became moot (`work withdraw <id>`).
- **Owner responses are decisions, not commands to the app.** The app does not merge or deploy. Act on a response in your own session, within the permissions the
  owner gave, record the outcome on the item, then consume the response.
  When answers arrive seconds apart (e.g. more than 5 in a minute), treat
  C-class answers in that burst as unconfirmed: do not act on them, and re-ask
  each one separately.
- **No routine acceptance asks.** For code-only or technically verifiable
  work, record the evidence and set the strongest verified stage (often
  `installed`); that is the end state, not a wait on the owner. Ask for
  acceptance only when the check is subjective (look and feel, family-facing
  behaviour).
- **Only the owner signs off `accepted`.** For a batch ready for subjective
  hands-on checks, use `work ask <slug> "<what to test>" --kind acceptance --also slug2,slug3`.
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
  `dropped` (400). If a dropped item should come back, raise it in the weekly
  chat check (as a C-class ask only if it is one) and wait for the owner to
  reopen it in the UI; an approve answer does not reopen it. Tokens may still drop items and update
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
  the item's `notes`.
- Record the removal on the item: clear `worktree` (`--worktree ""`) and add
  `work note <slug> "worktree removed <date>"`.
- A daily job on the Studio (`workspace-gc report --apply`, 08:00) removes
  class A checkouts itself: clean, every commit on the network remote, idle for
  48 hours, not in use and not the `worktree` of an active item. It also
  removes top-level workspace directories that have been empty for 6 hours. It
  writes what it removed and what remains (B after a push, C needing the owner)
  to `~/.local/state/workspace-gc/latest.txt` and keeps the item
  `workspace-gc-report` current. It needs no approval and never touches classes
  B, C or D. So a checkout you still need must have its path in an active
  item's `worktree` field, or hold the unpushed or uncommitted work that makes
  it B or C.

## Example

```sh
work upsert podcast-main-integration \
  --stage merged --commit f26cc99 --next-action "Deploy (A-class) and record installed" \
  --evidence "Commit=https://github.com/ephes/podcast/commit/f26cc99" --checked-at now
```
