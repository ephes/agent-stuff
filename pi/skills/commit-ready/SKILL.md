---
name: commit-ready
description: Use when the user asks whether current changes are ready to commit, asks for a pre-commit review, or wants commit readiness assessed without actually creating a commit. Inspect the diff, run appropriate checks, and verify tests, docs, specs, and generated artifacts are in sync.
---

# Commit Ready

Use this skill for assessment-only commit readiness checks.

This skill must not create a commit. It evaluates readiness, identifies gaps, and may fix clear, local sync issues if the user asked to prepare the work, but it does not run `git commit`.

## When To Use

Use this skill when the user asks for things like:
- "is this ready to commit?"
- "check this before I commit"
- "do a pre-commit pass"
- "review commit readiness"
- "make sure this is ready, but don't commit it"

If the user explicitly asks to create a commit, use `commit-workflow` instead.

## Workflow

1. Inspect the current worktree.
   Prefer:
   - `git status --short`
   - `git diff --stat`
   - targeted diffs for touched files

   Identify staged, unstaged, and untracked files.

2. Determine the intended scope.
   Identify:
   - touched implementation, tests, docs, specs, and generated files
   - whether the work appears complete or partial
   - whether unrelated changes are mixed into the worktree

   If the intended scope is unclear because unrelated changes are mixed together, call that out explicitly.

3. Check synchronization across the change.
   Look for likely follow-up needs in:
   - tests
   - feature or refactoring specs
   - `docs/`, `README.md`, or app-local docs
   - ADRs, migration notes, changelogs, or examples
   - API docs, schemas, or configuration docs
   - generated artifacts, snapshots, codegen output, or lockfiles when relevant

4. Run validation appropriate to the change.
   Prefer repo-native validation commands when available, such as:
   - `just check`
   - `make check`
   - `npm run check`
   - `bin/test`
   - `scripts/validate`

   Otherwise run the appropriate combination for the scope:
   - lint
   - typecheck
   - targeted tests first
   - broader tests when warranted

   If checks modify files, inspect the updated diff before concluding readiness.

5. Assess readiness.
   The work is commit-ready only when:
   - the implementation is coherent
   - relevant checks passed, or any intentionally skipped checks are explained
   - tests are adequate for the scope
   - docs and specs are in sync with the implementation
   - generated artifacts are refreshed when required
   - there are no known unresolved blockers

## Rules

- Do not create a commit.
- Treat docs and spec sync as part of commit readiness, not optional cleanup.
- Do not assume code-only changes are ready if they leave tests, docs, specs, or generated outputs inaccurate.
- Do not bless ambiguous or likely incorrect behavior by updating docs to match it; call out the mismatch instead.
- If unrelated changes are present, say so clearly and distinguish them from the likely intended commit scope.
- If the user asks only for assessment, prefer reporting issues over making broad edits.

## Output Contract

Always report:
- whether the change is commit-ready
- what checks or tests ran
- whether docs, specs, or generated artifacts appear in sync
- any blockers, risks, or ambiguous areas
- any clear next steps needed before commit

If you made any small fixes during preparation, state exactly what changed.

Do not commit, even if the change is ready.
