---
name: handoff-impl
description: This skill should be used when the user asks to "create an implementation handoff", "generate an implementation prompt", "hand off for implementation", "prepare implementation context", says "/handoff-impl", or wants to generate a prompt they can paste into another Claude Code session to perform implementation work.
---

# Implementation Handoff Prompt Generator

## Overview

Generate a self-contained implementation prompt that can be pasted into a fresh Claude Code CLI session. The receiving agent gets all the context it needs to implement a feature, fix a bug, or address review feedback without access to the original conversation.

Do not perform the implementation — only generate the prompt unless the user explicitly asks otherwise.

## When To Use

- After planning or designing work that a second agent will implement.
- After a review cycle: to hand off review TODOs to an implementing agent.
- When the user wants to delegate a well-defined piece of work to a fresh session.

## Workflow

### Step 1 — Inspect Current State

Before drafting the prompt, inspect the current repo context and session context:
- `git status --short`
- `git diff --stat`
- Targeted reads of files named by the user
- Prior review findings or agreed follow-up tasks already established in the session
- Local specs or design docs that define the requested work

### Step 2 — Determine Implementation Scope

Use this source-of-truth order:
1. **The user's explicit ask** — always takes priority
2. **Prior session findings, decisions, review feedback, or agreed follow-up tasks**
3. **Relevant specs, design docs, ADRs, backlog items, or companion-repo docs** already known in context
4. **The current diff and worktree** — as evidence, code-location discovery, and collateral-impact detection

If it is materially unclear which context defines the implementation target, ask the user a concise question instead of guessing.

### Step 3 — Load Minimum Relevant Context

Usually include:
- `CLAUDE.md` or `AGENTS.md` from the project
- The concrete specs or docs that define the requested slice
- The primary files to inspect first
- Prior findings or acceptance conditions that this implementation must satisfy

### Step 4 — Generate the Prompt

Produce the prompt inside a single fenced code block (` ```text `) so the user can copy it directly. Follow the template below.

If the current session already established useful facts (tests run, review findings, known risks), include them.

### Step 5 — Present to User

Output the prompt and tell the user to paste it into a fresh Claude Code session. If the prompt is for review feedback and the TODOs appear materially incomplete or contradictory, confirm with the user before generating.

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

## Prompt Template

The generated prompt MUST follow this structure. Adapt section content to the actual context — omit sections that don't apply, but never omit **Goal**, **Required Reading**, **Acceptance Criteria**, or **Implementer Report Contract**.

```text
You are implementing the work described below. This is an implementation task, not a review task. Read this context carefully before writing any code. Inspect the actual code before choosing an approach or design.

## Goal

[Clear description of what to build/change and why. Include motivation — user story, bug report, review feedback, etc. State the scope explicitly and why that is the scope now.]

## Required Reading

Study these files before starting. They contain patterns, interfaces, and context the implementation must align with.

- `/path/to/CLAUDE.md` — Project conventions and rules
- `/path/to/file.ts` — Contains the interface this implementation must conform to
- `/path/to/existing.ts` — Reference implementation following the same pattern
- `/path/to/tests/file.test.ts` — Existing tests that must continue to pass

## Constraints

[What must NOT change. Hard boundaries:]
- Do not modify the public API of X
- Do not add new dependencies
- Must maintain backward compatibility with Y
- [etc.]

## Failed Approaches — Do NOT Repeat

[What was already tried and why it didn't work. Include enough detail so the agent doesn't retry these:]

1. **[Approach name]** — [What was tried]. Failed because: [specific reason].
2. **[Approach name]** — [What was tried]. Failed because: [specific reason].

## Key Decisions

[Decisions already made. The implementing agent should follow these, not re-debate:]

| Decision | Chosen approach | Rationale |
|----------|----------------|-----------|
| [topic]  | [choice]       | [why]     |

## Tasks

Implement in this order. Keep changes scoped to the requested slice.

1. [ ] [Specific, actionable task with clear scope]
2. [ ] [Next task]
3. [ ] [etc.]

## Review Feedback to Address

[If applicable: specific review comments to address. Quote the reviewer's comment and note any clarifications.]

- **[file:line]**: "[Review comment]" → [What to do about it]
- **[file:line]**: "[Review comment]" → [What to do about it]

[If this is not addressing review feedback, omit this section.]

## Acceptance Criteria

The implementation is complete when:

1. All tasks above are done
2. [Specific functional requirement]
3. [Specific functional requirement]

Verify with:
- `npm test` — all tests pass
- `npm run lint` — no new warnings
- `npm run typecheck` — clean
- [any manual verification steps]

Update documentation and release notes when the change affects behavior, workflow, or user-facing usage. Treat missing or stale docs as incomplete work.

If anything in this context is unclear or you need additional information to proceed, ask before implementing. Do not guess at requirements or constraints.

## Implementer Report Contract

When done, report:
1. **Files changed** — list of modified, added, or deleted files
2. **Documentation** — which docs or release-note files changed, or an explicit statement that no doc changes were needed
3. **Tests** — which tests ran and their results
4. **Completeness** — whether the requested slice is complete or partial
5. **Summary** — concise explanation of what was implemented
6. **Follow-up risks** — remaining risks, cleanup, or next best action
```

## Rules

- Never generate a prompt that only says "implement X" without context. Always include required reading, constraints, and acceptance criteria.
- If the implementation scope is ambiguous, ask the user before generating.
- Use absolute file paths so the receiving agent can read files directly.
- Keep the prompt under 400 lines to preserve context window space in the receiving session.
- **Failed approaches are mandatory** when they exist in the conversation context. Omitting them wastes the next agent's time and tokens.
- For review feedback implementation, list every TODO explicitly. Do not summarize review comments — quote them so nothing is lost in translation.
- If the task is a follow-up to review feedback, carry the exact findings or acceptance conditions into the handoff instead of re-deriving scope only from the current diff.
- Include the instruction for the implementer to ask if unclear — the receiving agent should not guess at requirements.
- Tell the implementer to inspect the actual code before choosing an extraction or design.
- Tell the implementer to make code changes rather than stopping at analysis.
- Tell the implementer to keep changes scoped to the requested slice.
- If the task is a refactoring slice, keep the prompt focused on that slice rather than expanding into the whole program.
- If tests are a primary part of the change, call out the exact existing test modules the implementer should inspect first.
- Do not include large code blocks or file contents in the prompt. The receiving agent can read files itself.
- Include relevant docs, specs, or feature files already known from session context even if they are not in the diff.
- Order tasks by dependency — the implementing agent should be able to work through them sequentially.
- Tell the implementer to add or update tests as needed.
