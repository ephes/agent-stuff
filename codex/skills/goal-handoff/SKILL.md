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

   Capture intent, not procedure. When the user's ask is about an outcome
   ("make the UI feel like the reference app", "auth should be proper", "the
   editor should work"), the goal must encode that outcome and its quality bar,
   not a hand-derived checklist of files, feature rows, or setup steps. A goal
   that can be satisfied by green checks while the user-visible product still
   feels wrong is under-specified.

   Reference-product parity needs explicit comparison criteria:
   - Name the reference product, screenshots, repo, command, or workflow the
     next agent must compare against.
   - State that feature-count parity, smoke tests, or docs alignment are not
     completion proxies for look-and-feel parity.
   - Require evidence from the actual user-facing surface, such as screenshots,
     terminal captures, interaction transcripts, or browser/TTY automation.
   - Pin the exact invocation, runtime mode, environment, initial state, and
     keystroke/click sequence that counts. Do not let the next agent verify a
     special debug flag, alternate runtime, fake provider, or different trigger
     unless the user explicitly accepts that as the product path.
   - Include the reference's visible state fields in the quality bar when they
     matter (theme colors, provider/model label, working directory, footer,
     command palette trigger, selection highlight, and status text). "Similar
     structure" is not enough when the complaint names concrete visual or
     interaction differences.
   - Include at least one fake-completion blocker: e.g. "not done if the
     startup screen still differs materially from the reference", "not done if
     tab completion is absent", or "not done if the reference command list
     exists only in docs."

   For web UI/browser visual parity, require visual or render evidence that
   would catch missing CSS, fonts, images, JavaScript, layout, or interaction
   assets. A route returning 200, containing expected text, passing a content
   marker test, or showing a green smoke test is not enough when the user asked
   for a comparison frontend or visual parity. Require screenshots and/or
   computed-style/image-load assertions against the named reference, including
   representative image `naturalWidth > 0` and key typography/layout checks
   when relevant.

   For multi-route web UI parity, require evidence for every route/page in
   scope, or explicitly name sampled routes and why the unsampled routes are
   out of scope. Homepage-only visual checks cannot satisfy a site-wide parity
   goal. If a route has distinct widgets or layouts, require route-specific
   assertions for those widgets, such as profile images, tabs, cards,
   galleries, forms, calendars, lightboxes, or maps.

   Classify the goal before drafting:
   - Full-task goal — default when the user describes an outcome.
   - Slice goal — only when the user explicitly asked for a small named slice
     ("just the test-isolation step", "only the first move", etc.).

   If unclear whether the user wants a full-task goal or a slice goal, ask one
   concise question before drafting.

   For phased or long-running goals, classify each phase before drafting:
   - Required phases — must be completed before the goal can be marked done.
   - Conditional phases — must be evaluated and implemented only if their
     trigger conditions are met.
   - Out-of-scope phases — must not be pulled into the goal.

   If the user wants a full-task goal and the source plan contains optional,
   conditional, or later phases, state that boundary explicitly. Do not use
   vague wording such as "continue through the phases" when it lets the next
   agent stop after the first phase or treat optional work as required.

3. Draft the goal condition as a bounded objective, not a full prompt.
   Include only:
   - the concrete objective, sized to match user ambition
   - "done when" criteria that describe completion of the user's actual ask,
     not completion of a sub-step
   - qualitative quality bars when the user's goal is experiential, visual, or
     workflow parity
   - required phase/slice completion criteria for multi-slice goals
   - conditional phase trigger criteria when later phases are optional
   - non-completion criteria when premature stopping is a known risk
   - evidence requirements for critical verification, review, or commit gates
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
   - "done when" criteria that can be satisfied by documentation, scaffolding,
     a manual harness, or future-work notes when the user asked for implemented
     behavior
   - "done when" criteria that can be satisfied by a feature matrix or parity
     score when the user asked for the product to look, feel, or behave like a
     reference product
   - required phases that contain phrases like "future PR", "left for
     follow-up", "manual half", "outstanding", or "deferred" without making
     the phase incomplete or conditional
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

6. When precise length matters, verify the character count before final output.
   Report the count only when the user explicitly asks for it.

## Goal Condition Shape

Use compact prose or short bullets. Prefer a copy-ready goal body that starts
with the objective sentence directly, followed by sections only when they help:

```text
[one sentence naming the outcome, not the procedure]

Done when:
- [observable completion criterion, including qualitative quality bars when the
  user's intent has them]
- [criterion that explicitly fails the cheap fake-completion path]
- [verification criterion]

Constraints:
- [must-follow boundary]
- [out-of-scope boundary]
```

Omit headings when the goal is simple enough to fit in one paragraph. Do not
add an `Objective:` label unless the user explicitly asks for that format.

## Multi-Slice And Long-Running Guardrails

Use these guardrails when the user wants a goal that should continue across
several slices, phases, commits, or reviews.

- State the required phases by name or number. The goal is not complete until
  every required phase's done criteria are satisfied.
- State conditional phases separately. Include the trigger that promotes a
  conditional phase to required work, and state what evidence is enough to
  defer it.
- Add a continuation rule: after each clean slice, the agent must update its
  checklist and continue to the next incomplete required criterion. A slice
  completion is a checkpoint, not goal completion.
- Add non-completion examples tailored to the task. Common examples:
  "Do not stop after a scaffold", "Do not stop after Phase 0", "A manual test
  page is not browser verification", "A future-work note inside a required
  phase means the phase is incomplete", "A passing unit test is not enough when
  browser behavior is required."
- Require evidence for critical claims. Good evidence includes exact commands,
  browser automation output, test results, review findings, commit hashes, and
  an explicit remaining-checklist status.
- When browser, UI, audio, storage, worker, worklet, media-device, or end-to-end
  behavior is part of the goal, require an executed browser-level verification.
  A page or harness that can be run manually is not sufficient unless the user
  explicitly accepted manual verification.
- When web UI visual parity or a comparison frontend is part of the goal,
  require screenshots and/or computed browser evidence strong enough to catch
  missing CSS, fonts, images, JavaScript, layout, or interactions. Status/text
  checks and content-marker propagation are supporting checks, not visual
  parity proof.
- For multi-route sites or comparison frontends, require route/page coverage.
  A homepage screenshot plus status/text checks on other routes is not enough
  unless the user explicitly scoped the goal to the homepage. Distinct route
  widgets need route-specific checks, e.g. team profile images/tabs, gallery
  lightboxes, job cards, calendars, forms, or legal rich-text sections.
- When terminal UI, REPL, CLI, or shell interaction parity is part of the goal,
  require evidence from a real or pseudo-TTY session plus side-by-side
  comparison against the reference using the same user-facing invocation and
  exact keystrokes the user named. Unit tests are necessary but not sufficient
  for "looks and feels like X" claims. Completion triggered by `/` is not
  proven by a test that only sends Tab; the default product path is not proven
  by forcing an alternate input runtime; a real provider/model footer is not
  proven by a fake/test provider footer.
- When the user requires review gates, say when review must happen and what
  blocks progress. For example: unresolved Critical/Warning findings block
  committing and claiming the slice complete; Suggestions must be fixed or
  explicitly deferred.
- If the request follows a failed or premature run, generate a continuation
  goal that starts by auditing the existing work. Treat prior commits as
  incomplete until verified against the required criteria, list known gaps, and
  require the agent to fix them before continuing.

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
- For multi-slice goals, include a continuation rule unless the user explicitly
  wants only one slice.
- For goals with optional phases, name which phases are required and which are
  conditional; do not rely on "optional" alone.
- Include non-completion criteria when there is a risk of false completion by
  scaffolding, documentation, manual-only harnesses, feature matrices, parity
  scores, or future-work notes.
- Require evidence, not just claims, for browser/integration verification,
  terminal/REPL interaction verification, independent reviews, and completion
  of required phases.
- If the user asks for the goal condition only, return only the raw goal text:
  no fenced code block, no assistant preamble, no `Objective:` label, and no
  character-count suffix unless the user explicitly asks for a count.
- If the user asks for both a goal and a handoff prompt, keep the goal condition bounded and put detailed context in the starter prompt.
- If the scope is materially unclear, ask one concise question before drafting.
