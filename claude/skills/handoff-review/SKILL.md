---
name: handoff-review
description: This skill should be used when the user asks to "create a review handoff", "generate a review prompt", "hand off for review", "prepare review context", says "/handoff-review", or wants to generate a prompt they can paste into another agent session (Claude Code, Codex, or similar) to perform a code review.
---

# Review Handoff Prompt Generator

## Overview

Generate a self-contained review prompt that can be pasted into a fresh agent session (Claude Code, Codex, or any equivalent CLI). The receiving agent gets all the context it needs to perform a thorough, high-signal code review without access to the original conversation. Do not assume the receiving agent is the same kind as the current one — write the prompt agent-agnostically.

Do not perform the review — only generate the prompt unless the user explicitly asks otherwise.

## When To Use

- After completing implementation work that needs review by a second agent.
- During iterative review cycles: after addressing review feedback, to request re-review of specific changes.
- When the user wants to hand off any set of changes for independent review.

## Workflow

### Step 1 — Inspect Current State

Before drafting the prompt, inspect the current worktree and session context:
- `git status --short`
- `git diff --stat`
- `git diff -- <touched files>` for changed files when needed
- Targeted reads of files named by the user
- Prior review notes or follow-up findings already established in the session

### Step 2 — Determine Review Scope

Use this source-of-truth order:
1. **The user's explicit ask** — always takes priority
2. **Prior session findings, decisions, or iterative review-cycle context** — re-review targets, addressed feedback
3. **Relevant specs, docs, ADRs, or companion-repo docs** already known in context
4. **The current diff and worktree** — as evidence and file discovery, not the sole scope boundary

If it is materially unclear which context defines the review target, ask the user a concise question instead of guessing.

### Step 3 — Load Minimum Relevant Context

Usually include:
- `CLAUDE.md` or `AGENTS.md` from the project (for the receiving agent to load)
- The concrete specs or docs that define intended behavior
- The primary files to inspect first
- Prior findings or review targets to re-check when this is a follow-up review
- An explicit review lens when the user wants one (correctness, regression risk, maintainability, performance, security, or docs)

### Step 4 — Generate the Prompt

Produce the prompt inside a single fenced code block (` ```text `) so the user can copy it directly. Follow the template below.

If tests were run in the current session, include the commands and results.

When the reviewed project uses a workflow-learning capture command or similar workflow-learning capture, ask the reviewer to report summary-safe review metrics that can be recorded later: finding counts by severity; accepted, fixed, rejected, and deferred counts when known; whether counts are for this review round or cumulative across the review cycle; review round number or label when known; reviewer/implementer agent and model when known; and whether subagents materially affected the review. Do not ask for prompts, transcripts, tool output, secrets, or credentials.

### Step 5 — Present to User

Output the prompt and stop. Do not append any trailing commentary, paste instructions, or guidance about which agent to send it to — the user already knows where they intend to paste it, and trailers like "paste this into a fresh Claude Code session" confuse non-Claude agents (Codex, etc.) when the prompt is forwarded as-is. Ensure all file paths in the prompt are absolute.

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
- a reviewer output contract

Unless the user asks for something else, return only the reviewer prompt — no preface, no trailing commentary, no paste instructions.

## Prompt Template

The generated prompt MUST follow this structure. Adapt section content to the actual context — omit sections that don't apply, but never omit **Context**, **Scope**, **Review Criteria**, or **Reviewer Report Contract**.

```text
You are performing an independent code review. This is a review task, not an implementation task. Read this context carefully before reviewing any code.

## Context

[2-4 sentences: what was built/changed and why. Include the motivation — bug fix, feature, refactor, compliance, etc.]

## Scope

[List of files to review with brief description of what changed in each. Use absolute paths.]

- `/path/to/file.ts` — Added validation for X input
- `/path/to/other.ts` — Refactored Y to use Z pattern

## Context Files to Load First

[Project instructions and specs the reviewer should read before starting:]
- `/path/to/CLAUDE.md` — Project conventions and rules
- `/path/to/spec.md` — Feature specification this change implements

## Constraints

[What must not change. API contracts, backward compatibility, performance budgets, external system dependencies. Things the reviewer should NOT suggest changing.]

## Known Trade-offs

[Deliberate compromises. E.g., "Chose readability over micro-optimization in the hot path because profiling showed it's not a bottleneck."]

## Review Cycle Context

[If applicable: what previous review feedback was addressed, what was intentionally not changed and why. Name the prior findings that should be verified as resolved. Include the review round number or label when known, and state whether this review should close the cycle if clean. If this is the first review, omit this section.]

## Focus Areas

[Specific concerns for the reviewer to pay attention to. E.g., "The concurrency logic in worker.ts is subtle — please verify the lock ordering." Optionally specify a review lens: correctness, regression risk, maintainability, performance, security, or docs. Leave empty or omit if no specific concerns.]

## Verification

[Exact commands the reviewer can run:]
- `npm test` — all tests should pass
- `npm run lint` — no new warnings expected
- `npm run typecheck` — clean

## Review Criteria

Provide a high-signal review. Flag only issues you can verify from the code:

- **Critical**: Bugs, security vulnerabilities, data loss risks, broken contracts
- **Warning**: Logic errors, missing edge cases, unclear error handling
- **Suggestion**: Naming improvements, structural simplifications (only if clearly better)

Do NOT flag: style preferences, hypothetical issues you cannot verify, things covered by linters, or issues outside the listed scope. If unsure whether something is a real issue, investigate the surrounding code before flagging.

When reviewing changed functions, classes, or shared helpers, inspect surrounding file context — not only the diff hunks — to understand callers, callees, and collateral impact.

Verify that documentation and release notes are updated when behavior, workflow, or user-facing usage changed. Treat missing or stale docs as a finding.

If this repo documents workflow-learning or session-capture requirements for reviews, verify that the implementer can record the needed summary-safe review outcome through the project's documented capture commands, or can list it in the report when direct recording is not available. Include review round/scope metadata when known so per-round and cumulative metrics are not mixed. Do not ask for or include prompts, transcript bodies, tool output, secrets, credentials, or sensitive personal data.

If this is a clean second review or later and no relevant scope changed, say explicitly whether another review pass is warranted. Prefer stopping the review cycle after a clean second review unless risk, scope, or implementation changed enough to justify more review.

If anything in this context is unclear or you need additional information to review effectively, ask before proceeding.

## Reviewer Report Contract

Structure your output as follows:
1. **Findings** — ordered by severity (Critical → Warning → Suggestion), each with file and line references
2. **No findings** — if the review is clean, state this explicitly
3. **Documentation** — whether docs and release notes match the change, or an explicit statement that no doc changes were needed
4. **Open questions or assumptions** — anything you could not verify
5. **Completeness** — whether the change appears complete
6. **Next best follow-up** — suggested next action (merge, address findings, further review of X)
7. **Workflow-learning metrics** — when applicable, include finding counts by severity, accepted/fixed/rejected/deferred counts if known, whether those counts are per-review-round or cumulative, the review round number or label when known, reviewer/implementer agent and model if known, and any material subagent use. Keep this summary-safe and do not include prompts, transcript bodies, tool output, secrets, credentials, or sensitive personal data.
```

## Rules

- Never generate a prompt based solely on a git diff. Always include intent, constraints, and focus areas from the conversation context.
- Do not assume the current diff always defines the full review scope. Use the diff as a starting point, not an automatic limit on relevant context.
- If the scope of review is ambiguous, ask the user before generating.
- Use absolute file paths so the receiving agent can read files directly.
- Keep the prompt under 400 lines to preserve context window space in the receiving session.
- For re-reviews, explicitly state what changed since the last review and name the prior findings that should be verified — do not ask the reviewer to re-review everything.
- When the user is in an iterative review cycle, include that explicitly and carry forward the prior findings or review targets.
- For follow-up reviews, ask whether the review is clean enough to close the cycle; after a clean second review, do not request another pass unless scope or risk changed.
- Include the instruction for the reviewer to ask if unclear — the receiving agent should not guess.
- Do not include raw file contents or full diffs in the prompt. The receiving agent can read files itself.
- If the change is mostly tests, emphasize behavior preservation, helper design quality, and accidental semantics changes.
- If the change introduces shared helpers, ask the reviewer to check for over-abstraction, misleading names, and hidden coupling.
- Include relevant docs, specs, or feature files already known from session context even if they are not in the diff.
- Do not ask the reviewer to inspect the entire repository unless the request or observable impact genuinely requires it.
