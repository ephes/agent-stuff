---
name: review-handoff
description: >
  Generate a context-specific prompt for a second agent to review the current
  uncommitted changes. Use when the user asks to "handoff to reviewer", "write
  a review prompt", "prepare a code review for another agent", or similar.
  Inspects the real worktree - never produces a generic template.
---

# Review Handoff

Generate a prompt for a second agent to review the current changes.
Do not perform the review yourself unless the user explicitly asks.

## Invocation

Use `/skill:review-handoff` or ask naturally ("write me a review prompt",
"handoff to reviewer", etc.). Arguments after the command are treated as
additional instructions for the generated prompt.

## Workflow

1. **Gather changes** across all relevant repos.

   Run the helper script to get a unified view:

   ```bash
   bash scripts/gather-changes.sh [extra-repo-path ...]
   ```

   The script outputs git status and diff stats for the current repo and any
   extra repo paths passed as arguments. Use the `read` tool for targeted file
   inspection - never `cat` or `sed`.

2. **Infer scope** from the actual diff.

   Capture:
   - what changed (code, tests, docs, specs, or mixed)
   - primary files to inspect first
   - whether the change appears complete or partial
   - which specs, ADRs, or feature files are relevant

3. **Load project context** only when relevant.

   Examples:
   - `CLAUDE.md` or other project context files
   - spec or feature files referenced by the diff
   - `specs/` sources (feature specs, ADRs, ubiquitous language)
   - terminology files if naming or wording matters

4. **Draft the reviewer prompt** specific to the current change.

5. **Include test results** if tests were run in the current session.

## Prompt Requirements

The generated prompt must include:

- A one-line review task statement.
- An explicit statement that this is a **review task, not an implementation
  task**.
- Repo scope using **relative paths** (relative to the project root or home),
  not absolute paths.
- The current uncommitted change set, grouped by repo when multi-repo.
- Context files to load first.
- Primary files to inspect first.
- A "What changed" summary derived from the actual diff.
- Review focus areas specific to the change.
- Specific things to check closely.
- Validation already run (commands + results).
- Required output format (see below).

## Path Convention

Use `~/`-relative or project-relative paths in the generated prompt. Absolute
paths make prompts fragile and non-portable. For example:

- `~/workspaces/ws-merge-frontend/emerge` -> `~/workspaces/ws-merge-frontend/emerge` (ok, tilde-relative)
- Prefer referring to files by name when unambiguous: "inspect `feedback_model.py`"

## Review Standard

Tell the reviewer to:

- Review, not implement.
- Use the `read` tool to inspect files.
- Prioritize bugs, regressions, hidden coupling, incorrect abstractions, and
  maintainability risks over style.
- Inspect touched files first.
- Inspect relevant `specs/` sources when they define the intended behavior.
- Run targeted tests if useful (headless via `QT_QPA_PLATFORM=offscreen` for
  PySide UI tests).
- Report findings first, ordered by severity, with file and line references.

## Output Contract

Unless the user asks for something else, return **only the reviewer prompt**.

The reviewer prompt must instruct the reviewer to produce:

1. **Findings** - ordered by severity, with file and line references. If none,
   say so explicitly.
2. **Open questions or assumptions**.
3. **Completeness assessment** - whether the change appears complete.
4. **Suggested follow-up** - the next best action.

After outputting the prompt, offer to copy it to the clipboard.

## Rules

- Do not output a generic template if the worktree can be inspected.
- Do not ask the reviewer to inspect the entire repository unless the diff
  genuinely requires it.
- Prefer concrete touched files over broad module lists.
- When `specs/` files are relevant, include specific paths in the prompt.
- If the change is mostly tests, emphasize behavior preservation, helper
  design quality, and accidental semantics changes.
- If the change introduces shared helpers, ask the reviewer to check for
  over-abstraction, misleading names, and hidden coupling.
- If you cannot determine enough context, say so and draft the best prompt
  from observable changes.
