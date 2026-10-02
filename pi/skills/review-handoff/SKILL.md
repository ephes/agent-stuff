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

## Review behavior to carry into every prompt

Read the canonical [cross-agent-review-cycle](../../../codex/skills/cross-agent-review-cycle/SKILL.md)
when drafting; resolve installed symlinks to the source before following the link.
Include its resolved path in required reading, but also carry the applicable
instructions below into the generated prompt so a fresh session can act without
reconstructing policy. This is one independent review round; the driver owns
adjudication, repairs, further rounds, and commit authorization.

- Continue only while review/repair has substantial risk-reduction value; no
  fixed round cap, mandatory second pass, or loop merely to obtain `CLEAN`.
  Accepted material findings need repair, required checks, and fresh independent
  scoped re-review. Low-value/advisory closure needs explicit disposition and
  rationale; never relabel unresolved findings or advisory closure `CLEAN`.
- For follow-up or resumed context, carry the accepted finding baseline, each
  finding's severity/status/evidence and fixed/rejected/deferred rationale,
  reviewed revision or snapshot, repair delta, unchanged invariants, reviewer
  selection, and pending checks. Do not infer closure from a clean current diff
  or a narrower `CLEAN`; unresolved earlier Critical/Warning findings survive.
- For Claude/Pi repair rounds, the driver preserves `--record-baseline`, uses
  the returned snapshot as `--baseline-ref`, reuses the slice id, and starts
  a fresh run directory; prompt wording alone does not scope the bundle.
  Re-review the accepted findings plus repair delta. Classify new findings as
  repair-caused, directly coupled, or pre-existing/unrelated. Expand the gate
  for every Critical, repair-caused/coupled Warning, or finding invalidating
  acceptance criteria, safety boundaries, persisted evidence, or the claimed
  fix. Record other concerns as follow-up rather than recursive scope growth;
  an unresolved Warning still needs owner acceptance before commit, and a
  Critical cannot be deferred by the agent. Record why any whole-slice reopening
  is necessary.
- Carry explicit reviewer/model/effort choices; otherwise use canonical
  selection. Claude uses the installed `claude-review-loop` harness, default
  `claude-opus-5-5` at medium; Pi must use `openai-codex/gpt-6-sol` through its
  installed harness. If a required reviewer, model, or authentication is
  unavailable (including a harness that rejects that model), report the blocked
  gate without substitution. Failed/invalid attempts are not valid reviews.
- Report this round's evidence and findings separately from cumulative cycle
  status. State unresolved items, advisory dispositions, limits, and why another
  round would or would not reduce demonstrated risk; the driver applies the
  canonical commit gate. For a harness context, preserve its strict schema:
  the driver records cycle dispositions outside the reviewer verdict.

## Workflow

1. **Gather changes** across all relevant repos.

   Run the helper script to get a unified view:

   ```bash
   bash scripts/gather-changes.sh [extra-repo-path ...]
   ```

   The script outputs git status and diff stats for the current repo and any
   extra repo paths passed as arguments. Use the `read` tool for targeted file
   inspection - never `cat` or `sed`.

2. **Determine scope** from the user request, prior findings and decisions,
   relevant specs, then the diff as evidence and file discovery. A resumed
   review must retain earlier unresolved findings even when the diff is empty.

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
   Return the raw prompt text only, with no surrounding fenced code block,
   markdown wrapper, preface, trailing commentary, paste instructions, or
   follow-up offer. The prompt itself may use Markdown headings and lists.

5. **Include test results** if tests were run in the current session.

6. **Include workflow-learning details** when the reviewed project documents
   session or workflow capture. Ask for summary-safe review metrics that can be
   recorded later: finding counts by severity, accepted/fixed/rejected/deferred
   counts when known, whether metrics are per-round or cumulative, the review
   round number or label when known, reviewer/implementer agent and model when
   known, and material subagent use. Do not ask for prompts, transcripts, tool
   output, secrets, or credentials.

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
- Review-cycle context when this is a follow-up review, including the review
  round number or label when known.
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
- Carry the review behavior above into the prompt; assess further review by
  demonstrated risk reduction and cumulative unresolved findings.

## Output Contract

Unless the user asks for something else, return **only the raw reviewer
prompt**.

The reviewer prompt must instruct the reviewer to produce:

1. **Findings** - ordered by severity, with file and line references. If none,
   say so explicitly.
2. **Open questions or assumptions**.
3. **Completeness assessment** - whether the change appears complete.
4. **Suggested follow-up** - the next best action.
5. **Workflow-learning metrics** when applicable - finding counts by severity,
   accepted/fixed/rejected/deferred counts when known, whether counts are
   per-round or cumulative, the review round number or label when known,
   reviewer/implementer agent and model when known, and any material subagent
   use. Keep this summary-safe.

## Rules

- Do not output a generic template if the worktree can be inspected.
- Do not wrap the generated prompt in a fenced code block, quotation block,
  assistant preamble, title, or follow-up offer.
- Do not ask the reviewer to inspect the entire repository unless the diff
  genuinely requires it.
- Prefer concrete touched files over broad module lists.
- Carry the accepted finding baseline and repair delta into follow-up reviews;
  do not reopen a whole-slice audit without a recorded reason.
- When `specs/` files are relevant, include specific paths in the prompt.
- If the change is mostly tests, emphasize behavior preservation, helper
  design quality, and accidental semantics changes.
- If the change introduces shared helpers, ask the reviewer to check for
  over-abstraction, misleading names, and hidden coupling.
- If you cannot determine enough context, say so and draft the best prompt
  from observable changes.
