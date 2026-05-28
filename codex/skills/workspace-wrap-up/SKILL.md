---
name: workspace-wrap-up
description: Use when the user asks to wrap up, finalize, commit, sync, promote, merge back, or push a multi-repo workspace, especially ops-control/ops-library workspaces created by just workspace-create. Validate the touched repos, commit each repo separately, run configured workspace sync/promote commands, and report pushed refs without discarding user changes.
---

# Workspace Wrap-Up

## Purpose

Finalize work that may span multiple repositories in a local workspace. This
skill coordinates commit readiness, commits, workspace promotion, and pushes.

Use this skill when the user says things like:
- "wrap it up"
- "commit and push everything"
- "merge this workspace back"
- "promote the workspace"
- "finalize these changes"

## Safety Rules

- Do not run destructive commands such as `git reset --hard`, `git checkout --`,
  `git clean`, forced worktree removal, or force-push unless the user explicitly
  asks for that exact operation.
- Do not overwrite, revert, or stage unrelated user changes.
- Do not commit or push if the user only asked for an assessment.
- If commit/push/promote intent is ambiguous, report the wrap-up plan and ask
  for confirmation.
- Commit separately per repository.
- Use non-interactive git commands.
- Prefer existing repo/workspace commands over ad hoc copying or manual branch
  surgery.

## Workflow

1. Identify the workspace and changed repositories.
   - Start from `pwd`.
   - Use `git rev-parse --show-toplevel` for the current repo.
   - For ops workspaces, also inspect the workspace root, `ops-control`,
     `ops-library`, and relevant service repos under `PROJECTS_ROOT` or
     `/Users/jochen/projects`.
   - Run `git status --short` and `git diff --stat` in each candidate repo.

2. Load local wrap-up rules.
   - Read root `AGENTS.md` when present.
   - Read repo-local `AGENTS.md` for changed repos.
   - For ops-control workspaces, read `references/ws-ops.md`.

3. Separate intentional changes from generated or unrelated changes.
   - If unrelated dirty files are present, leave them unstaged and call them out.
   - If formatter or generated files changed because validation ran, include
     them only when they are part of making the repo pass its own checks.

4. Validate commit readiness.
   - Use the existing `commit-workflow` guidance for each changed repo.
   - Ensure docs and release notes are synchronized when behavior, workflow, or
     user-facing usage changed.
   - Run targeted checks first, then broad checks required by the local context.
   - Do not skip a documented required check silently; report explicit blockers.

5. Commit.
   - Stage only the files belonging to the current repo's intentional change.
   - Commit with a concise present-tense message.
   - Report each repo and commit hash.

6. Sync, promote, and push.
   - For ops-control workspaces, use the configured workspace commands from
     `references/ws-ops.md`.
   - Prefer fast-forward-only promotion commands.
   - If a repo is not managed by the workspace promotion command, push it with
     normal git only after confirming branch/upstream state.

7. Report the wrap-up outcome using the output contract below.

## Ops-Control Workspaces

When working in a workspace created by `just workspace-create`, read
`references/ws-ops.md` before running sync/promote/push commands.

## Output Contract

When done, report:
- Repositories committed, with hashes
- Repositories pushed or promoted, with target refs
- Validation evidence
- Documentation/release-note status
- Dirty or unpushed leftovers
- Any explicit follow-up, such as deployment or live verification
