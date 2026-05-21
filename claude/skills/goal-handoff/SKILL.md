---
name: goal-handoff
description: This skill should be used when the user asks to "create a goal handoff", "generate a goal prompt", "draft a goal condition", "write a continuation objective", "produce a second-agent goal statement", says "/goal-handoff", or wants a compact goal/objective they can paste into a bounded goal field (such as a 4000-character objective) for another agent session.
---

# Goal Handoff Prompt Generator

## Overview

Generate a compact goal condition that can be pasted into a bounded goal/objective field for another agent session. The output is tuned to fit a strict character limit — by default 4000 characters — while still carrying the objective, success criteria, and constraints the next agent needs.

This skill is for goal tracking and continuation, not full implementation or review context. It is **not** `handoff-impl` and **not** `handoff-review`:

- If the user needs a complete second-agent coding prompt, use `handoff-impl`.
- If the user needs a code review prompt, use `handoff-review`.
- Use `goal-handoff` when the destination is a short objective field and a full handoff prompt would overflow it.

Do not perform the work — only generate the goal condition unless the user explicitly asks otherwise.

## Workflow

### Step 1 — Inspect Current State

Before drafting, inspect the current repo context and session context. Prefer:

- `git status --short`
- Targeted reads of files named by the user
- Targeted reads of active backlog, planning, review, or summary files that define the goal
- Targeted reads of project instructions such as `CLAUDE.md` or `AGENTS.md` when they materially affect completion
- Prior session facts already established in conversation

### Step 2 — Determine Goal Scope

Use this source-of-truth order:

1. **The user's explicit goal request** — always takes priority
2. **Current session decisions, review outcomes, blockers, or accepted follow-ups**
3. **Local backlog, specs, planning docs, release notes, or project instructions**
4. **The current worktree** — as evidence of in-progress work

If the scope is materially unclear, ask one concise question before drafting.

### Step 3 — Draft the Goal Condition

Draft a bounded objective, not a full prompt. Include only:

- The concrete objective
- The success condition or "done when" criteria
- Critical constraints and out-of-scope boundaries
- Required verification commands when known
- Any blocking facts the next agent must not rediscover

### Step 4 — Fit the Destination Limit

Keep the goal condition safely under the destination limit.

- **Hard cap:** 4000 characters when no other cap is specified.
- **Target:** 3000-3500 characters for a 4000-character field.
- If the first draft is too long, compress by removing background, file lists, and low-risk details **before** removing success criteria.

### Step 5 — Split Overflow

If useful context does not fit, split the response into:

- **Goal condition** — the bounded text that fits in the goal/objective field.
- **Optional starter prompt** — extra context the user can paste into the chat body after creating the goal.

Do not put overflow context into the goal condition.

### Step 6 — Report the Count

When precise length matters, verify the character count before final output and report it next to the goal condition.

## Goal Condition Shape

Use compact prose or short bullets. Prefer this structure:

```text
Objective: [one sentence]

Done when:
- [observable completion criterion]
- [verification criterion]

Constraints:
- [must-follow boundary]
- [out-of-scope boundary]
```

Omit headings when the goal is simple enough to fit in one paragraph.

## Rules

- Return a goal condition, not a generic template.
- Do not include full diffs, raw file contents, long file inventories, or copied review reports.
- Do not list every relevant file unless the goal cannot be understood without them.
- Use absolute paths only for files the next agent must open first; otherwise prefer repo-relative descriptions to save characters.
- Preserve decisions already made in the session instead of re-opening them.
- State deferred work explicitly when it prevents accidental scope expansion.
- Include exact verification commands when known and important.
- If the user asks for the goal condition only, return only one fenced `text` block plus the character count.
- If the user asks for both a goal and a handoff prompt, keep the goal condition bounded and put detailed context in the starter prompt.
- If the scope is materially unclear, ask one concise question before drafting.
