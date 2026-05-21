---
name: goal-handoff
description: Use when the user asks for a compact goal prompt, goal condition, create_goal objective, continuation objective, or second-agent goal statement, especially when the destination has a strict character limit such as 4000 characters. Generate a concise, context-specific goal condition from the current worktree, session context, and relevant planning docs without producing a full implementation or review handoff.
---

# Goal Handoff

## Overview

Generate a compact goal condition that can be pasted into a bounded goal/objective field for another agent session.

This skill is for goal tracking and continuation, not full implementation context. If the user needs a complete second-agent coding prompt, use `implement-handoff`; if they need a review prompt, use `review-handoff`.

## Workflow

1. Inspect the current context before drafting.
   Prefer:
   - `git status --short`
   - targeted reads of files named by the user
   - targeted reads of active backlog, planning, review, or summary files that define the goal
   - targeted reads of project instructions such as `AGENTS.md` when they materially affect completion
   - prior session facts already established in conversation

2. Determine the goal scope with this source-of-truth order:
   - the user's explicit goal request
   - current session decisions, review outcomes, blockers, or accepted follow-ups
   - local backlog, specs, planning docs, release notes, or project instructions
   - the current worktree as evidence of in-progress work

3. Draft the goal condition as a bounded objective, not a full prompt.
   Include only:
   - the concrete objective
   - the success condition or "done when" criteria
   - critical constraints and out-of-scope boundaries
   - required verification commands when known
   - any blocking facts the next agent must not rediscover

4. Keep the goal condition safely under the destination limit.
   - Hard cap: 4000 characters when no other cap is specified.
   - Target: 3000-3500 characters for a 4000-character field.
   - If the first draft is too long, compress by removing background, file lists, and low-risk details before removing success criteria.

5. If useful context does not fit, split the response into:
   - `Goal condition` - the bounded text that fits in the goal/objective field.
   - `Optional starter prompt` - extra context the user can paste into the chat body after creating the goal.
   Do not put overflow context into the goal condition.

6. When precise length matters, verify the character count before final output. Report the count next to the goal condition.

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
