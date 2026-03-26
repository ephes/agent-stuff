---
name: implement-handoff
description: Use when the user asks for a prompt for a second agent to implement a change, feature, refactoring slice, or bugfix. Generate a self-contained, context-specific implementation prompt based on the current worktree, requested target, session context, and relevant specs or documentation already known in context.
---

# Implement Handoff

## Overview

Generate a self-contained implementation prompt that can be pasted into a fresh Codex or CLI coding-agent session.

The goal is a concrete implementation handoff, not a generic coding template.

## When To Use

Use this skill when the user asks for things like:
- "write me a prompt for a second agent to implement this"
- "handoff to implementer"
- "draft an implementation prompt"
- "prepare a second-agent prompt for the next slice"

## Workflow

1. Inspect the current repo context and the current session context before drafting the prompt.
   Prefer:
   - `git status --short`
   - `git diff --stat`
   - targeted reads of files named by the user
   - targeted reads of prior review findings or agreed follow-up tasks already established in the session
   - local specs or design docs that define the requested work

2. Determine the implementation scope with this source-of-truth order:
   - the user's explicit ask
   - prior session findings, decisions, review feedback, or agreed follow-up tasks
   - relevant specs, design docs, ADRs, backlog items, terminology docs, or companion-repo docs already known in context
   - the current diff and worktree as evidence, code-location discovery, and collateral-impact detection
   If it is materially unclear which context defines the implementation target, ask the user a concise question instead of guessing.

3. Load the minimum relevant context.
   Usually include:
   - `AGENTS.md`
   - the concrete specs or docs that define the requested slice
   - the primary files to inspect first
   - prior findings or acceptance conditions that this implementation must satisfy

4. Draft a second-agent prompt that is specific to the requested implementation.
   Output the prompt inside a single fenced `text` code block so the user can copy it directly.
   Use absolute file paths throughout the prompt.

5. If the current session already established useful facts, include them.
   Examples:
   - tests already run
   - review findings to address
   - known follow-up risks

## Generated Prompt Must Include

- a one-line implementation task statement
- an explicit statement that this is an implementation task, not a review task
- a short statement of the implementation scope and why that is the scope now
- the primary repo or subdirectory scope
- context files or docs to load first
- primary files to inspect first
- explicit constraints or boundaries
- failed approaches when they exist in session context
- key decisions that should not be re-debated
- the intended slice or feature goal
- an ordered task breakdown when the work benefits from it
- any prior review findings or acceptance conditions that define the slice
- concrete implementation expectations
- exact verification commands when they are known
- documentation and release-note expectations when behavior, workflow, or user-facing usage changed
- an implementer report contract

Unless the user asks for something else, return only the implementation prompt.

The implementer report contract should usually ask for:
- which files changed
- which docs or release-note files changed, or an explicit statement that no doc changes were needed
- which tests ran
- whether the requested slice is complete or partial
- a concise explanation of what was implemented
- follow-up risks or next best cleanup

## Prompt Template

The generated prompt should follow this structure. Adapt the content to the actual context. Omit sections that do not apply, but never omit `Goal`, `Required Reading`, `Acceptance Criteria`, or `Implementer Report Contract`.

```text
You are implementing the work described below. This is an implementation task, not a review task. Read this context before writing code. Inspect the actual code before choosing an approach or design.

## Goal

[Clear description of what to build or change and why. State the scope explicitly and why that is the scope now.]

## Required Reading

[Absolute paths only. Files the implementer should read before starting.]

- /absolute/path/to/AGENTS.md - Project instructions
- /absolute/path/to/file.ts - Existing interface or pattern to follow
- /absolute/path/to/file.test.ts - Existing tests that must keep passing

## Constraints

[What must not change. API contracts, backward compatibility, performance budgets, dependency limits, intentionally out-of-scope work.]

## Failed Approaches - Do NOT Repeat

[What was already tried and why it failed. This section is mandatory when failed approaches exist in session context. Omit only when there were no failed approaches.]

1. [Approach] - [what was tried]. Failed because: [specific reason].

## Key Decisions

[Decisions already made. The implementer should follow these rather than re-debating them.]

| Decision | Chosen approach | Rationale |
| --- | --- | --- |
| [topic] | [choice] | [why] |

## Tasks

[Ordered tasks when the work benefits from them. Keep changes scoped to the requested slice.]

1. [ ] [Specific task]
2. [ ] [Specific task]

## Review Feedback To Address

[If this work is driven by review findings, list each finding or acceptance condition explicitly. Omit otherwise.]

- [file:line] - [review finding or required fix]

## Acceptance Criteria

The implementation is complete when:

1. [Specific requirement]
2. [Specific requirement]

## Verification

[Exact commands the implementer should run when they are known.]

- `command` - [expected result]

Update docs or release notes when behavior, workflow, or user-facing usage changed. Treat missing or stale docs as incomplete work.

If anything in this context is unclear or you need more information to proceed, ask before implementing. Do not guess at requirements or constraints.

## Implementer Report Contract

When done, report:
1. Files changed - list modified, added, or deleted files.
2. Documentation - which docs or release-note files changed, or state that no doc changes were needed.
3. Tests - which tests ran and their results.
4. Completeness - whether the requested slice is complete or partial.
5. Summary - concise explanation of what was implemented.
6. Follow-up risks - remaining risks, cleanup, or next best action.
```

## Rules

- Do not output a generic implementation template if the current request and local context can be inspected.
- Prefer concrete file paths over broad package descriptions.
- Use absolute file paths so the receiving agent can read files directly in a fresh session.
- Return the generated prompt inside a single fenced `text` code block.
- Keep the generated prompt under 400 lines.
- Include relevant docs, feature files, or specs already known from session context even if they are not in the diff or not in the same repo.
- If it is materially unclear what context should be included for the implementation handoff, ask the user directly instead of silently narrowing scope.
- Failed approaches are mandatory when they exist in session context. Omitting them wastes the next agent's time and tokens.
- Tell the implementer to inspect the actual code before choosing an extraction or design.
- Tell the implementer to make code changes rather than stopping at analysis.
- Tell the implementer to keep changes scoped to the requested slice.
- Tell the implementer to add or update tests as needed.
- Tell the implementer to update docs or release notes when the change affects behavior, workflow, or user-facing usage.
- If the task is a refactoring slice, keep the prompt focused on that slice rather than expanding into the whole program.
- If the task is driven by review feedback, list each finding or acceptance condition explicitly rather than summarizing it loosely.
- If the task is a follow-up to review feedback, carry the exact findings or acceptance conditions into the handoff instead of re-deriving scope only from the current diff.
- If tests are a primary part of the change, call out the exact existing test modules the implementer should inspect first.
- Order tasks by dependency so the receiving agent can work through them sequentially.
- Do not include large code blocks or full file contents in the prompt. The receiving agent can read files directly.
- If the required scope is ambiguous, say so briefly and draft the best prompt from the observable context.
