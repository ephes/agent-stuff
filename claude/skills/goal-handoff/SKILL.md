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

**Capture intent, not procedure.** When the user's ask is about an *outcome*
("make the code structure good", "the UI should feel like the legacy one",
"auth should be proper", "the editor should work"), the goal must encode that
outcome — not a hand-derived recipe of files, directories, or steps. A goal
that lists exact paths and exact transformations turns an intent ("a sane
structure") into a literal ("these directories exist"). The next agent then
happily produces the literal artifact while missing the actual quality bar.

When summarizing intent:

- Prefer "the resulting X is good/usable/maintainable, judged by Y" over
  exhaustive lists of files to move or create.
- Name the design references the next agent should compare against
  (legacy UI, sibling project, existing spec) rather than re-deriving the
  shape inline.
- If both the destination shape and the source spec are known, prefer
  pointing at the source spec by name. Re-stating a tree in the goal
  body invites flattening errors (an `a/b/c/` source becoming `a/c/` in
  the goal). When the spec doc itself is wrong, say so and require it
  fixed as part of the work.

**Block fake-completion.** When the work has multiple plausible "looks done"
end states that aren't actually done — e.g., directories renamed but code
still imports the old paths; UI scaffolded but unusable; auth migrated but
still issuing old tokens; tests passing because they were narrowed — the goal
must include a criterion that fails the cheap version. Examples:

- "Editing every field in the legacy admin via the new admin produces the
  same logical content shape" (not "all admin routes return 200").
- "A reviewer who used the legacy admin recognizes the new admin as the
  same product" (not "the new admin renders").
- "Session cookies issued, no JWT/HS256 tokens anywhere in the new flow"
  (not "auth works").

Verifiable hard gates and qualitative quality bars can coexist; both should
appear in "Done when" when the user's intent has both.

**Reference-product parity needs direct evidence.** When the user says a
product should look, feel, or behave like a reference product, the goal must
make comparison against that reference a required completion gate. Name the
reference product, screenshots, repo, command, or workflow the next agent must
compare against. Feature-count parity, smoke tests, docs alignment, and a
green test suite are not completion proxies for reference-product parity.

For UI, terminal UI, REPL, CLI, or shell interaction parity, include evidence
from the actual user-facing surface: screenshots, terminal captures,
interaction transcripts, browser automation, or pseudo-TTY automation. Unit
tests can support the claim, but they cannot be the whole claim when the ask is
"make it feel like X."

Pin the exact invocation, runtime mode, environment, initial state, and
keystroke/click sequence that counts. Do not let the next agent verify a
special debug flag, alternate runtime, fake provider, or different trigger
unless the user explicitly accepts that as the product path. Include the
reference's visible state fields in the quality bar when they matter: theme
colors, provider/model label, working directory, footer, command palette
trigger, selection highlight, and status text. "Similar structure" is not
enough when the complaint names concrete visual or interaction differences.

For web UI/browser visual parity, require visual or render evidence that would
catch missing CSS, fonts, images, JavaScript, layout, or interaction assets. A
route returning 200, containing expected text, passing a content marker test, or
showing a green smoke test is not enough when the user asked for a comparison
frontend or visual parity. Require screenshots and/or computed-style/image-load
assertions against the named reference, including representative image
`naturalWidth > 0` and key typography/layout checks when relevant.

For multi-route web UI parity, require evidence for every route/page in scope,
or explicitly name sampled routes and why the unsampled routes are out of
scope. Homepage-only visual checks cannot satisfy a site-wide parity goal. If a
route has distinct widgets or layouts, require route-specific assertions for
those widgets, such as profile images, tabs, cards, galleries, forms,
calendars, lightboxes, or maps.

The goal should fail the cheap version explicitly. Examples:

- "Not done if the startup screen still differs materially from the reference
  startup screen, aside from branding."
- "Not done if typing Tab does not show the same class of command completion
  the reference product shows."
- "Not done if the reference opens the command menu on `/` but the tested
  implementation only opens something after Tab or under a forced runtime."
- "Not done if a fake/test provider appears in the default product footer when
  the reference shows a real provider/model."
- "Not done if the command list exists only in docs or tests but not in the
  running product."
- "Not done if the agent reports a parity matrix score instead of comparing
  the actual UI/workflow the user named."

**Tree-flattening rule.** When the source spec uses a directory tree,
preserve every intermediate directory in any path you do put in the goal.
Listing leaf names without their parent layers (`a/c/` from a source of
`a/b/c/`) is a flattening error, not a compression. Prefer naming the
spec doc over re-stating its tree.

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
- Qualitative quality bars when the user's goal is experiential, visual,
  workflow, or reference-product parity
- Non-completion criteria when a cheap proxy could look done while missing the
  user-visible outcome
- Evidence requirements for critical verification, review, or commit gates
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
- "Done when" criteria that can be satisfied by documentation, scaffolding,
  feature matrices, parity scores, or future-work notes when the user asked for
  implemented product behavior
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

### Step 6 — Character Count

When precise length matters, verify the character count before final output.
Report it only when the user explicitly asks for it.

## Goal Condition Shape

Use compact prose or short bullets. Prefer a copy-ready goal body that starts
with the objective sentence directly, followed by sections only when they help:

```text
[one sentence naming the outcome, not the procedure]

Done when:
- [observable completion criterion, including qualitative quality bars when
  the user's intent has them — e.g. "the new admin is recognizable as the
  same product as the legacy admin"]
- [criterion that explicitly fails the cheap fake-completion path]
- [verification criterion / hard gate]

Constraints:
- [must-follow invariant]
- [out-of-scope boundary the user actually agreed to defer]
```

Omit headings when the goal is simple enough to fit in one paragraph. Avoid
turning the "Done when" list into a checklist of files that exist; that is a
procedure, not a completion criterion. Do not add an `Objective:` label unless
the user explicitly asks for that format.

## Long-Running Goal Guardrails

Use these guardrails when the goal should continue across several slices,
commits, reviews, or UI/workflow checkpoints:

- State the required phases by name. The goal is not complete until every
  required phase's done criteria are satisfied.
- Add a continuation rule: after each clean slice, the agent must update its
  checklist and continue to the next incomplete required criterion. A slice
  completion is a checkpoint, not goal completion.
- Require evidence for critical claims. Good evidence includes exact commands,
  browser or pseudo-TTY automation output, screenshots, terminal captures, test
  results, review findings, commit hashes, and an explicit remaining-checklist
  status.
- For terminal UI, REPL, CLI, or shell interaction parity, require side-by-side
  evidence from the same user-facing invocation and exact keystrokes the user
  named. Completion triggered by `/` is not proven by a test that only sends
  Tab; the default product path is not proven by forcing an alternate input
  runtime; a real provider/model footer is not proven by a fake/test provider
  footer.
- For web UI visual parity or comparison frontends, require screenshots and/or
  computed browser evidence strong enough to catch missing CSS, fonts, images,
  JavaScript, layout, or interactions. Status/text checks and content-marker
  propagation are supporting checks, not visual parity proof.
- For multi-route sites or comparison frontends, require route/page coverage. A
  homepage screenshot plus status/text checks on other routes is not enough
  unless the user explicitly scoped the goal to the homepage. Distinct route
  widgets need route-specific checks, e.g. team profile images/tabs, gallery
  lightboxes, job cards, calendars, forms, or legal rich-text sections.
- When the request follows a premature or suspicious completion claim, require
  the next agent to audit existing work first and treat prior commits as
  incomplete until verified against the user's actual criteria.
- When review gates are required, say what blocks progress. Unresolved
  Critical/Warning findings block claiming the goal complete; Nits/Suggestions
  must be fixed or explicitly deferred with rationale.

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
