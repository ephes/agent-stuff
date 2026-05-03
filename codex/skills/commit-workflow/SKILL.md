---
name: commit-workflow
description: Use when the user asks to commit changes, prepare work for commit, check whether a change is ready to commit, or finalize the current worktree. Inspect the current changes, bring implementation, tests, and relevant specs or documentation into sync if needed, validate the result, and only then commit when appropriate.
---

# Commit Workflow

## Overview

Handle commit preparation as a workflow, not a single action.

Depending on the user's request, this skill should either:
- assess whether the current worktree is commit-ready, or
- actively bring it into commit-ready shape by fixing missing sync or validation gaps, then commit

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

2. Determine what the current change actually includes.
   Identify:
   - touched code, tests, docs, or spec files
   - whether the work looks complete or partial
   - whether the user asked only for assessment or for an actual commit

3. Check for documentation and spec synchronization.
   Look for places that may need updates, such as:
   - feature or refactoring specs
   - `specs/docs/`
   - app-local docs directories such as `docs/` or `frontend/docs/`
   - top-level docs
   - ADRs
   - RTM inputs or generated artifacts when relevant

4. If implementation changes imply docs or spec changes and those updates are missing:
   - make the updates if the required change is clear and local to the task
   - otherwise stop and ask the user, because ambiguous documentation updates should not be invented

5. Run the right validation for the scope.
   Prefer targeted tests first.
   Use broader checks when the change warrants them.

6. Reassess commit readiness.
   The change is only commit-ready when:
   - implementation is coherent
   - tests are adequate for the scope
   - docs/specs are in sync with the current implementation state
   - there are no known unresolved blockers

7. Check whether the repo has workflow-learning capture instructions.
   If `AGENTS.md`, project docs, or the user's request mention commands such as
   `pipy-session workflow`, make sure important implementation/review/subagent
   facts from the current session are not lost before committing:
   - record or remind the user to record implementer/reviewer roles and models
   - record or remind the user to record review finding counts and closure
     counts when a review happened
   - record or remind the user to record material subagent use
   - record or remind the user to add a workflow evaluation when the session
     taught something about an agent/model pattern
   Do not include prompts, transcript bodies, tool output, secrets,
   credentials, or sensitive personal data in workflow-learning fields.
   Do not block an otherwise ready commit solely because private session
   capture is unavailable; prefer a concise note in the final response when
   the workflow event cannot be appended from the current context.

8. If the user asked to commit and the work is ready:
   - create the commit using a non-interactive git command
   - respect repo-specific rules for split commits across repos
   - if files under `specs/` belong to a separate docs or specs repo in this codebase, commit them in that repo rather than assuming the code-repo commit is sufficient
   - report the commit hash or hashes

## Rules

- Treat docs/spec sync as part of commit readiness, not optional cleanup.
- Do not assume code-only changes are complete if they leave specs or developer docs inaccurate.
- Do not invent broad documentation changes without evidence from the implementation.
- If a required documentation update is ambiguous, ask instead of guessing.
- Respect local `AGENTS.md` instructions and repo-specific commit rules.
- If multiple repos are involved, commit them separately when required and report both hashes.
- If `specs/` files live in a separate docs or specs repo for the current project, commit them there and do not treat that as satisfied by a code-repo commit alone.
- Never commit while known sync gaps or validation blockers remain.
- Treat workflow-learning capture as session hygiene when the project asks for it, but do not invent uncertain model names, review counts, or subagent facts.

## Output Contract

When responding to the user, clearly state:
- whether the change is commit-ready
- what you fixed before commit, if anything
- what tests or checks ran
- whether docs/specs were already in sync or were updated
- whether workflow-learning capture was recorded, was not applicable, or still needs a follow-up
- any blockers that prevented committing

If a commit was created, report:
- the repo or repos committed
- the commit hash or hashes

If the user asked to commit but blockers remain, say so plainly and do not commit.
