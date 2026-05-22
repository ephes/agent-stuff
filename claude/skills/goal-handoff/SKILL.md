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

**Match the ambition of the user's request.** If the user asks to "do the
refactor according to the layout doc and make tests green," the goal must
describe the whole refactor, not a hand-picked starter slice. The skill's job
is to compress the user's stated objective into a bounded field, not to
substitute a smaller objective the agent considers safer.

**Classify the goal before drafting:**

- **Full-task goal** — the user wants the entire piece of work done. Default
  assumption when the user describes an outcome (a finished refactor, a
  released feature, a passing test suite) rather than a single step.
- **Slice goal** — the user explicitly asked for a small, named slice
  ("just do the test-isolation slice", "only the first step", "stop after
  moving X").

Pick **slice** only when the user said so. Otherwise pick **full-task**.

If the scope is materially unclear — especially whether the user wants a
full-task goal or a slice goal — ask one concise question before drafting.

### Step 3 — Draft the Goal Condition

Draft a bounded objective, not a full prompt. Include only:

- The concrete objective, sized to match the user's ambition (Step 2)
- The success condition or "done when" criteria that describe completion of
  *the user's actual ask*, not completion of a sub-step
- Critical constraints that describe invariants (behavior that must not break,
  data that must not be lost, gates that must keep passing) — **not** deferred
  work the user actually wanted included
- Required verification commands when known, sized to the goal: a full-task
  refactor goal needs the full gate (`just check`, `just test-e2e`, etc.); a
  narrow slice may only need a focused command
- Any blocking facts the next agent must not rediscover

**Scope-reduction red flags** — if the draft contains any of these, stop and
re-check Step 2 (or ask the user) before continuing:

- The phrases "first safe slice", "minimal slice", "prep slice", or
  "without broader X" when the user did not ask for slicing
- A constraints list whose items match the obvious next implementation steps
  in the linked planning doc (that is the work, not the boundary)
- "Done when" criteria that finish before the user-visible outcome is
  achievable
- A constraints section longer than the success criteria

Constraints describe invariants the next agent must respect *while doing the
work*; they do not describe work the next agent must skip.

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
- State deferred work explicitly **only when the user agreed to defer it**.
  Do not invent deferrals to make the goal look smaller or safer.
- Never silently downscope an ambitious user request to a "first slice"
  goal. If you believe slicing is wiser, ask the user before drafting.
- Include exact verification commands when known and important.
- If the user asks for the goal condition only, return only one fenced `text` block plus the character count.
- If the user asks for both a goal and a handoff prompt, keep the goal condition bounded and put detailed context in the starter prompt.
- If the scope is materially unclear, ask one concise question before drafting.
