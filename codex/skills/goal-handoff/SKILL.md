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

   Match the ambition of the user's request. If the user describes a finished
   outcome (a completed refactor, a released feature, a passing test suite),
   the goal must describe the whole outcome, not a hand-picked starter slice.
   The skill compresses the user's stated objective into a bounded field; it
   does not substitute a smaller objective the agent considers safer.

   Classify the goal before drafting:
   - Full-task goal — default when the user describes an outcome.
   - Slice goal — only when the user explicitly asked for a small named slice
     ("just the test-isolation step", "only the first move", etc.).

   If unclear whether the user wants a full-task goal or a slice goal, ask one
   concise question before drafting.

3. Draft the goal condition as a bounded objective, not a full prompt.
   Include only:
   - the concrete objective, sized to match user ambition
   - "done when" criteria that describe completion of the user's actual ask,
     not completion of a sub-step
   - critical constraints that describe invariants (behavior, data, gates
     that must not break) — not deferred work the user actually wanted
   - required verification commands sized to the goal
   - any blocking facts the next agent must not rediscover

   Scope-reduction red flags — stop and re-check scope (or ask the user) if
   the draft contains any of these:
   - "first safe slice", "minimal slice", "prep slice", or "without broader X"
     when the user did not request slicing
   - a constraints list whose items match the obvious next implementation
     steps in the linked planning doc
   - "done when" criteria that finish before the user-visible outcome is
     achievable
   - a constraints section longer than the success criteria

   Constraints describe invariants the next agent must respect while doing
   the work; they do not describe work the next agent must skip.

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
- State deferred work explicitly only when the user agreed to defer it. Do not
  invent deferrals to make the goal look smaller or safer.
- Never silently downscope an ambitious user request to a "first slice" goal.
  If slicing seems wiser, ask the user before drafting.
- Include exact verification commands when known and important.
- If the user asks for the goal condition only, return only one fenced `text` block plus the character count.
- If the user asks for both a goal and a handoff prompt, keep the goal condition bounded and put detailed context in the starter prompt.
- If the scope is materially unclear, ask one concise question before drafting.
