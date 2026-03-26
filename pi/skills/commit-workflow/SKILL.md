---
name: commit-workflow
description: Use when the user asks to commit changes, prepare current work for commit, or assess whether the worktree is ready. Inspect the diff, identify the intended scope, run appropriate checks, ensure docs, specs, and generated artifacts stay in sync, and commit only when the change is coherent and validated.
---

# Commit Workflow

Handle commit preparation as a workflow, not a single command.

Depending on the user's request, this skill should either:
- assess whether the current worktree is commit-ready
- bring the worktree into commit-ready shape by fixing clear gaps
- create the commit once the change is ready

## When To Use

Use this skill when the user asks for things like:
- "commit this"
- "prepare this for commit"
- "is this ready to commit?"
- "clean this up and commit it"
- "finalize these changes"

## Workflow

1. Inspect the current worktree.
   Prefer:
   - `git status --short`
   - `git diff --stat`
   - targeted diffs for touched files

   Identify staged, unstaged, and untracked files.

2. Determine the intended scope of the change.
   Identify:
   - touched implementation, tests, docs, specs, and generated files
   - whether the work looks complete or partial
   - whether the user asked only for an assessment or for an actual commit
   - whether unrelated changes are mixed into the worktree

   If unrelated changes are present and the intended commit scope is unclear, stop and ask before staging or committing.

3. Check for synchronization requirements.
   Look for places that may need updates, such as:
   - tests
   - feature or refactoring specs
   - `docs/`, `README.md`, or app-local docs
   - ADRs, migration notes, changelogs, or examples
   - API docs, schemas, or configuration docs
   - generated artifacts, snapshots, codegen output, or lockfiles when relevant

4. Update clear, local sync gaps.
   If implementation changes imply docs, specs, tests, or generated outputs and the required update is narrow and directly supported by the task or diff, make the update.

   If the required update is ambiguous, broad, or would require inventing intent, stop and ask the user instead of guessing.

5. Run validation appropriate to the change.
   Prefer repo-native validation commands when available, such as:
   - `just check`
   - `make check`
   - `npm run check`
   - `bin/test`
   - `scripts/validate`

   If there is no canonical check command, run the right combination for the scope:
   - lint
   - typecheck
   - targeted tests first
   - broader tests or full-suite checks when warranted

   If validation commands modify files, re-inspect the diff before deciding the work is ready.

6. Reassess commit readiness.
   The change is only commit-ready when:
   - the implementation is coherent
   - the relevant checks passed, or any intentionally skipped checks are explained
   - tests are adequate for the scope
   - docs and specs are in sync with the implementation
   - generated artifacts are refreshed when required
   - there are no known unresolved blockers

7. If the user asked to commit and the work is ready:
   - stage only the intended files
   - write a concise commit message that reflects the actual change
   - create the commit using a non-interactive git command
   - respect local `AGENTS.md` instructions and repo-specific multi-repo commit rules
   - report the commit hash or hashes

## Rules

- Treat docs and spec sync as part of commit readiness, not optional cleanup.
- Do not commit unrelated modified files without user confirmation.
- Do not assume code-only changes are complete if they leave tests, docs, specs, or generated outputs inaccurate.
- Do not invent broad documentation, product behavior, or specification changes without evidence from the implementation or explicit user direction.
- If the implementation appears inconsistent with the task, spec, or existing docs, stop and ask instead of updating docs to bless a possibly wrong change.
- If multiple repos are involved, commit them separately when required and report each hash.
- Never commit while known sync gaps or validation blockers remain.

## Output Contract

When responding to the user, clearly state:
- whether the change is commit-ready
- what you fixed before commit, if anything
- what checks or tests ran
- whether docs, specs, or generated artifacts were already in sync or were updated
- any blockers that prevented committing

If a commit was created, report:
- the repo or repos committed
- the commit hash or hashes
- the commit message summary

If the user asked to commit but blockers remain, say so plainly and do not commit.
