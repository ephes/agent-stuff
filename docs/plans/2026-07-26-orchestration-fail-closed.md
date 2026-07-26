# Orchestration Must Fail Closed — Root Cause And Simplification

Status: proposal
Date: 2026-07-26

## What happened

A six-phase implementation workflow reported "completed" having silently skipped
its most important phase. Phases 0, 2, 3, and 4 landed; Phase 1 — the redaction
and descriptor-safe-read work that the entire plan existed to deliver — was
never attempted. `just check` was green, the tree was clean, and the run
summary read like a success.

## Proximate cause

A burst of provider 529s killed three consecutive agents:

| agent | ran | transcript | outcome |
|-------|-----|-----------|---------|
| `fix:phase-0` | 09:36:05 → 09:49:08 (13 min) | 398 KB | **work completed and committed** (`7a284ab`), then died before returning |
| `implement:phase-1` | 09:49:08 → 09:52:58 (4 min) | 19 KB | died having produced nothing |
| `verify:phase-1` | 09:52:58 → 09:57:11 (4 min) | 18 KB | died having produced nothing |

The next agent started at 09:57:11 and succeeded. The outage was roughly eight
minutes wide and hit exactly the wrong eight minutes.

Transient provider errors are not the interesting part. The interesting part is
that the orchestration treated them as success.

## Root causes

### 1. A fail-open guard

The workflow script's per-phase gate was:

```js
const blocking = (verdict?.findings || []).filter(f => f.severity !== 'suggestion')
if (verdict && (!verdict.phase_ok || blocking.length)) { /* dispatch a fix */ }
else { /* record the phase as fine and continue */ }
```

When the verifier itself died, `verdict` was `null`, the condition
short-circuited to `false`, and the phase was recorded as passing. **A missing
verdict was indistinguishable from a passing verdict.**

`agent()` returns `null` on a terminal API error. Every `null` in that script —
implementer report, verifier verdict — flowed into a string interpolation or a
truthiness check that degraded quietly.

### 2. No preconditions between phases

Nothing asserted that Phase N's artifacts existed before Phase N+1 began. The
existence of `shared/review_harness/gitio.py` was the whole question, and it was
never asked. Phases 2, 3, and 4 then built on a tree missing Phase 1.

Constraint worth recording: workflow scripts have no filesystem access, so a
precondition cannot be a plain `fs.existsSync`. It has to be a schema-forced
agent answer that the script gates on.

### 3. Findings could not escalate past their own phase

The Phase 3 and Phase 4 verifiers **both** detected and reported that Phase 1
had not landed. The signal was correct, arrived twice, and was discarded —
because findings were routed only to a phase-local fix agent, which had neither
the scope nor the authority to implement a missing phase. There was no path for
"the problem is outside my phase."

### 4. The real one: the invariant lived in prose, not in code

Fail-closed-on-missing-verdict is not a new lesson here. It is already written
down, three times over:

- `docs/review-cycle-log.md`, 2026-07-10 consolidated entry: "a review gate must
  distinguish findings from infrastructure failure. Schema-invalid or missing
  verdicts, provider errors, stalls, crashes … all produce failed states and
  exit 2; only schema-consistent CLEAN can exit 0."
- `docs/review-cycle-log.md`, 2026-07-16: "apply the same fail-closed sentinel
  rule to delegated implementation sessions as to reviews … rather than
  inferring completion."
- `cross-agent-review-cycle/SKILL.md`, added earlier the same day: "treat 'no
  output and no file writes' as failure, and say so, rather than reporting the
  slice as still in flight."

Both harnesses *implement* this correctly for the reviewer subprocess. The
orchestration script was hand-written from scratch and inherited none of it.

This is the same root cause as the finding that motivated the plan in the first
place: redaction existed on one side only because the invariant lived in a log
entry instead of in shared code. The apparatus is excellent at recording lessons
and poor at putting them where they execute.

## The fix

Encode the invariants in a reusable template, not in another document.

1. **`mustAgent()` instead of `agent()`** for anything load-bearing: retry a
   `null` result twice with backoff, then **throw**. A dead agent aborts its
   phase rather than passing it. Transient 529s become a retry, not a skip.
2. **Every gate compares against an explicit pass value.** `verdict?.phase_ok
   === true` and nothing weaker. `null`, `undefined`, and a malformed object are
   all failures.
3. **Verifier schema gains `blocking_outside_this_phase: string[]`.** Non-empty
   aborts the whole run and names what is missing. This is what would have
   stopped the run at Phase 2, and again at Phase 3, and again at Phase 4.
4. **A precondition agent per phase** — one cheap schema-forced call that
   answers "do phase N-1's named artifacts exist in the tree?" — since scripts
   cannot touch the filesystem themselves.
5. **The final report is derived from the tree, not from agent text.** The last
   step lists actual commits and artifacts and returns them structured. Any
   human-facing claim about what landed comes from that, never from an
   implementer's self-report.
6. **Save it as a named workflow** in `.claude/workflows/` so the next phased
   implementation starts from the hardened template instead of a blank script.

## Simplification

The failure is worth fixing, but the bigger finding from treating this as a test
of the approach is that the approach is heavier than the work it delivers.

### The plan review targeted the wrong artifact

Four Codex rounds were spent on a planning document. Rounds 2–4 mostly hardened
prose. The genuinely valuable findings — the natural-exit descendant leak, the
untracked-file TOCTOU, the context-file TOCTOU — all came from the reviewer
reading **code**, incidentally, while checking whether the plan's claims were
true.

Cheaper path, same result: run one code audit of the two harnesses first, then
write a short plan from its findings. The plan would have been right initially
instead of corrected toward correctness across four rounds, at roughly a quarter
of the cost.

### The plan is larger than its content

After review, the plan's actual substance is: make Pi's bundle as safe as
Claude's, bring Pi's lock and lifecycle to parity, fix two shared defects, and
extract nothing. That is one shared module plus adoption on both sides. Five
phases, a reassessment gate, a decision record, and a contract matrix are
ceremony around a change whose essence is "put the safe implementation somewhere
shared and use it twice."

### The deployment barrier may be net-negative

It added code to both CLIs, a `justfile` recipe, documentation in three places,
and an autouse `HOME` redirect in both `conftest.py` files that *reduced* the
barrier's own end-to-end coverage — all to make a rare manual operation safe.
The simpler answer is not to run the review gate from a mutable checkout that is
being edited. Reconsider before merge.

### Two harnesses is the root complexity

Everything else is compensation for it. Either accept two harnesses and stop
planning to merge them, or do the extraction. Paying the coordination cost of
both is the current state.

### The log has stopped functioning as a mechanism

2,500 lines, 119 entries, and its central lesson still failed to reach the code
that needed it. Distil the live rules into a short document the skills link to,
and archive the incidents.

## Decisions

Decided 2026-07-26:

- **Barrier: dropped.** Removed from both CLIs, the `justfile`, both harness
  SKILLs, the README, and both `cross-agent-review-cycle` mirrors, along with
  the autouse `HOME` fixture it forced into both suites
  (`harness-safety-parity` @ `7111937`). Cutover safety is now operator
  discipline: do not edit the checkout the review gate runs from.
- **Extraction: dropped, not deferred.** The reassessment gate, contract matrix,
  decision record, and successor plan are gone. Two hardened harnesses is the
  end state. `shared/review_harness/` remains for redaction, git invocation, and
  descriptor-safe reads, because those are security primitives that must not
  diverge.

Still open:

1. Adopt the hardened workflow template? (recommended: yes, it is small)
2. Distil the review log into a short rules document the skills link to, and
   archive the incidents?
