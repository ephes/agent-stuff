---
name: review-handoff
description: Use when the user asks for a prompt for a second agent to review the current changes, such as "handoff to reviewer", "write me a code review prompt", or similar. Generate a self-contained, context-specific reviewer prompt based on the current worktree, the user request, and relevant specs or docs already known in context, not a generic template.
---

# Review Handoff

## Overview

Generate a self-contained review prompt that can be pasted into a fresh Codex or CLI coding-agent session.

Do not perform the review unless the user explicitly asks for that instead.

## When To Use

Use this skill when the user asks for things like:
- "write me a prompt for a second agent to do a code review"
- "handoff to reviewer"
- "draft a reviewer prompt"
- "prepare a second-agent review prompt"

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
  `claude-opus-5-5` at medium; Pi must use `openai-codex/gpt-6.1-sol` through its
  installed harness. If a required reviewer, model, or authentication is
  unavailable (including a harness that rejects that model), report the blocked
  gate without substitution. Failed/invalid attempts are not valid reviews.
- Report this round's evidence and findings separately from cumulative cycle
  status. State unresolved items, advisory dispositions, limits, and why another
  round would or would not reduce demonstrated risk; the driver applies the
  canonical commit gate. For a harness context, preserve its strict schema:
  the driver records cycle dispositions outside the reviewer verdict.

## Workflow

1. Inspect the current worktree and the current session context before drafting the prompt.
   Prefer:
   - `git status --short`
   - `git diff --stat`
   - `git diff -- <touched files>`
   - targeted reads of files named by the user
   - targeted reads of prior review notes or follow-up findings already established in the session
   - targeted reads of changed files when needed
   - discoverable project-local planning docs, specs, ADRs, backlog files, release notes, or design docs that define intended behavior

2. Determine the review scope with this source-of-truth order:
   - the user's explicit ask
   - prior session findings, decisions, or iterative review-cycle context
   - relevant project-local instructions, specs, feature files, ADRs, backlog items, terminology docs, release notes, or companion-repo docs already known or discoverable from the repo context
   - the current diff and worktree as evidence, changed-file discovery, and collateral-impact detection
   If it is materially unclear which context defines the review target, ask the user a concise question instead of guessing.

3. Load the minimum relevant context.
   Usually include:
   - `AGENTS.md`
   - the concrete planning docs, specs, ADRs, or docs that define intended behavior
   - the primary files to inspect first
   - prior findings or review targets to re-check when this is a follow-up review
   - an explicit review lens when the user wants one, such as correctness, regression risk, maintainability, performance, security, or docs

4. When the target repo documents summary-safe session reflection and the review
   is for planning-heavy, workflow-related, model/provider-related, backlog
   grooming, or boundary-selection work, inspect existing lessons before
   drafting. Prefer read-only, summary-safe commands such as:
   - `uv run pipy-session reflect --json`
   - `uv run pipy-session search <topic> --json`
   Use only metadata, event summaries, and Markdown summaries by default. Do
   not include raw transcript bodies, prompts, tool output, secrets,
   credentials, or sensitive personal data in the generated prompt.

5. Draft a second-agent prompt that is specific to the current review.
   Return the raw prompt text only, with no surrounding fenced code block,
   markdown wrapper, introductory heading, explanation, or trailing offer to
   copy it. The prompt itself may use Markdown headings and lists.
   Use absolute file paths throughout the prompt.

6. If tests were run in the current session, include the commands and results.

7. When the reviewed project uses a workflow-learning capture command or similar
   workflow-learning capture, ask the reviewer to report review metrics that
   can be recorded later:
   - finding counts by severity
   - accepted, fixed, rejected, and deferred counts when known, with a note about whether counts are for this review round or cumulative across the review cycle
   - review round number or label when known, for example first review, follow-up, second review, or closeout
   - reviewer agent/model and implementer agent/model when known
   - whether subagents materially affected the review
   Keep this request summary-safe; do not ask for prompts, transcripts, tool
   output, secrets, or credentials.

## Generated Prompt Must Include

- a one-line review task statement
- an explicit statement that this is a review task, not an implementation task
- a short statement of the review scope and why that is the scope now
- the primary repo or subdirectory scope
- context files or docs to load first
- primary files to inspect first
- explicit constraints or boundaries
- known trade-offs when they exist
- review cycle context when this is a follow-up review
- review round/scope context when known, including whether this is a first review, follow-up, second review, or closeout
- review focus areas or an explicit review lens
- exact verification commands when they are known
- review criteria with severity tiers and explicit "do not flag" guidance
- documentation and release-note verification when behavior, workflow, or user-facing usage changed
- workflow-capture verification when the target repo documents review or session-learning requirements
- relevant summary-safe session-learning lessons when the target repo documents reflection and the review scope calls for it
- a reviewer output contract

Unless the user asks for something else, return only the raw reviewer prompt.

The reviewer output contract should ask for:
- findings first, ordered by severity
- file and line references for each finding
- an explicit statement when there are no findings
- documentation or release-note verification when applicable
- open questions or assumptions
- whether the change appears complete
- the next best follow-up
- summary-safe review metrics suitable for workflow-learning capture when applicable
- whether review metrics are per-round or cumulative when an iterative review cycle is in progress
- review round number or label when known

## Prompt Template

The generated prompt should follow this structure. Adapt the content to the actual context. Omit sections that do not apply, but never omit `Context`, `Scope`, `Review Criteria`, or `Reviewer Report Contract`. The fenced block below documents the template only; do not include the surrounding fence in the generated output.

```text
You are performing an independent code review. This is a review task, not an implementation task. Read this context before reviewing any code.

## Context

[2-4 sentences describing what changed and why. Include the motivation and the scope boundary for this review.]

## Scope

[Absolute paths only. List the primary files to review first and what changed in each.]

- /absolute/path/to/file.ts - [what changed]
- /absolute/path/to/other.ts - [what changed]

## Context Files to Load First

[Project instructions, planning docs, specs, ADRs, release notes, or companion-repo docs that define intended behavior.]

- /absolute/path/to/AGENTS.md - Project instructions
- /absolute/path/to/spec.md - Feature or behavior spec

## Constraints

[What the reviewer should treat as fixed boundaries. API contracts, backward compatibility, external dependencies, performance budgets, intentional scope exclusions.]

## Known Trade-offs

[Deliberate compromises that should be understood as intentional. Omit if not applicable.]

## Review Cycle Context

[If this is a follow-up review, name the prior findings or review targets to verify and note what was intentionally not changed. Include the review round number or label when known, and carry the accepted baseline, repair delta, unchanged invariants, and unresolved dispositions. Omit only on a first review.]

## Focus Areas

[Specific concerns or an explicit review lens such as correctness, regression risk, maintainability, performance, security, or docs. Omit if there is no special focus.]

## Verification

[Exact commands the reviewer can run when they are known.]

- `command` - [expected result]

## Review Criteria

Provide a high-signal review. Flag only issues you can verify from the code and surrounding context.

- Critical: bugs, security vulnerabilities, data loss risks, or broken contracts
- Warning: logic errors, missing edge cases, unclear error handling, or maintainability risks likely to cause defects
- Suggestion: clearly better naming or structural improvements that stay within scope

Do NOT flag:
- style preferences
- hypothetical issues you cannot verify
- things already enforced by linters or formatters
- issues outside the listed scope

When reviewing changed functions, classes, tests, or shared helpers, inspect surrounding file context and relevant callers or callees rather than only diff hunks.

Verify docs or release notes when behavior, workflow, or user-facing usage changed. Treat missing or stale docs as findings.

If this repo documents workflow-learning or session-capture requirements for reviews, verify that the implementer can record the needed summary-safe review outcome through the project's documented capture commands, or can list it in the report when direct recording is not available. Include review round/scope metadata when known so per-round and cumulative metrics are not mixed. Do not ask for or include prompts, transcript bodies, tool output, secrets, credentials, or sensitive personal data.

Apply the review behavior above: recommend continuation only for demonstrated risk reduction, and report advisory closure and unresolved findings truthfully.

If anything in this context is unclear or you need more information to review effectively, ask before proceeding.

## Reviewer Report Contract

Structure your output as follows:
1. Findings - ordered by severity: Critical, Warning, Suggestion. Include file and line references for each finding.
2. No findings - if the review is clean, state this explicitly.
3. Documentation - whether docs and release notes match the change, or state that no doc changes were needed.
4. Open questions or assumptions - anything you could not verify.
5. Completeness - whether the change appears complete for the stated scope.
6. Next best follow-up - the most useful next action.
7. Workflow-learning metrics - when applicable, include finding counts by severity, accepted/fixed/rejected/deferred counts if known, whether those counts are per-review-round or cumulative, the review round number or label when known, reviewer/implementer agent and model if known, and any material subagent use. Keep this summary-safe and do not include prompts, transcript bodies, tool output, secrets, credentials, or sensitive personal data.
```

## Rules

- Do not output a generic review template if the current diff can be inspected.
- Do not assume the current diff always defines the full review scope.
- Use the diff as a starting point, not an automatic limit on relevant context.
- When the user is in an iterative review cycle, include that explicitly in the handoff and name the prior findings or review targets that should be verified.
- Carry the review behavior above into the prompt and assess closure against the cumulative finding state, not the round number.
- Prefer concrete touched files over broad module lists.
- Use absolute file paths so the receiving agent can read files directly in a fresh session.
- Return the generated prompt as raw text only. Do not wrap it in a fenced
  code block, quotation block, assistant preamble, title, or follow-up offer.
- Keep the generated prompt under 400 lines.
- Include relevant project-local instructions, planning docs, feature files, release notes, or specs already known from session context or discoverable from repo guidance, even if they are not in the diff or not in the same repo.
- If it is materially unclear what context should be included for the review, ask the user directly instead of silently narrowing scope.
- Do not ask the reviewer to inspect the entire repository unless the request or observable impact genuinely requires it.
- Do not include raw file contents or full diffs in the prompt. The receiving agent can read files directly.
- Tell the reviewer to inspect surrounding file context, not only diff hunks, when changed functions, classes, or shared helpers have meaningful callers or callees.
- Tell the reviewer to verify docs or release notes when the change needs them, and to treat missing or stale docs as findings.
- Tell the reviewer what not to flag so the review stays high-signal.
- When the target repo records workflow-learning events, ask for review metrics that map to the repo's documented workflow-learning commands.
- For iterative review cycles, ask whether review metrics are for the current round or cumulative across the cycle.
- For iterative review cycles, ask for the review round number or label when it can be inferred from context.
- If the change is mostly tests, emphasize behavior preservation, helper design quality, and accidental semantics changes.
- If the change introduces shared helpers, ask the reviewer to check for over-abstraction, misleading names, and hidden coupling.
- If you cannot determine enough context from the worktree, say so briefly and draft the best prompt from the observable changes.
