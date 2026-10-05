---
name: work-ledger
description: Use when coordinating multi-project agent work through the owner's private work ledger (github.com/ephes/work-ledger) - reading what is in flight or waiting on the owner, or recording a stage change, owner question, blocker or evidence after verifying it. Provider-neutral; shared by Claude, Codex and Pi coordinators.
---

# Work Ledger

The private repository `ephes/work-ledger` (normally `~/projects/work-ledger`)
is the source of truth for multi-project agent work. Chat history, worker
reports and hosted dashboards are not. Its `README.md` is authoritative for the
schema; this skill is the working summary.

## When to use

- **Read** before choosing, resuming or reporting on cross-project work, and when
  the owner asks what is in flight or what waits on them.
- **Update** when an item changes stage, gains or loses an owner question,
  becomes blocked, or new evidence (commit, receipt, install) exists.
- Workers inside one project slice do not edit the ledger; their coordinator
  does, after verifying the report.

## Items

One file per item: `ledger/items/<id>.yaml`, where `id` equals the file name.
Required: `id`, `title`, `project`, `stage`, `owner`, `needs_owner`,
`next_action`, `updated_at`. Optional: `repo` (network URL, never a local path),
`worktree`, `branch`, `commit` (quoted), `owner_question` (required when
`needs_owner: true`), `blocked_reason` (required for `blocked`), `evidence`
(repository-relative paths that exist, or http(s) URLs), `notes`.

`owner` is who acts next: `claude-subagent`, `codex`, `herdr:<workspace label>`,
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

## Rules

- **Verify before writing.** Check git (`git ls-remote`, `merge-base
  --is-ancestor`, `status`), herdr, CI or device state yourself. Worker reports
  and receipts are claims; record what you observed, and say in `notes` what
  you could not verify.
- **`updated_at` is when the facts were checked**, in UTC
  (`2026-10-05T15:40:00Z`), not when the file was edited. Do not bump it on a
  wording edit, and never set it to now for facts you did not re-check.
- **Owner questions** are one concrete, answerable question each
  (`Merge f26cc99 into main?`), set `needs_owner: true` with `owner: jochen`.
  When answered, record the decision in `notes`, clear `needs_owner`, and
  update `next_action`. Do not re-ask a question the ledger shows answered.
- **Never record secrets**: no credentials, tokens, cookies, raw financial or
  résumé data, or raw terminal logs. Summarize and link a receipt instead.
- **One item per file; touch only the items you verified.** Other coordinators
  edit the same repository: pull first, and on a conflict re-read their change
  instead of overwriting it.

## Workflow

```sh
cd ~/projects/work-ledger && git pull --ff-only
# edit ledger/items/<id>.yaml; add receipts under receipts/<campaign>/ if needed
just validate
just build          # optional local look at dashboard/dist/index.html
git add ledger receipts
git commit -m "ledger: <id> pushed at 8f205eb"
git push
```

Commit messages name the item and the change (`ledger: podcast-main-integration
needs owner merge decision`). The dashboard is built with `just build`;
`dashboard/dist/` is build output and is never committed.
