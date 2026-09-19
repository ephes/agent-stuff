---
name: cross-agent-review-cycle
description: Use before committing an implementation slice when a configurable different-family reviewer should inspect the slice, or when coordinating value-driven fix/re-review cycles with Claude, Codex, or Pi. Claude and Pi reviews use their supervised review harnesses.
---

# Cross-Agent Review Cycle

## Purpose

Run a value-driven independent review loop before committing an implementation
slice. Default to a different model family from the implementer. An explicit user
choice overrides this default; record same-family reviews accurately.

## Reviewer Selection

- Default to a different model family; honor an explicit user-selected reviewer.
- `REVIEWER_AGENT` may override the default reviewer. Supported values:
  `auto`, `claude`, `codex`, and `pi`. The legacy values `claude-plan` and
  `claude-no-tools` are accepted only as aliases for `claude`; they no longer
  select separate Claude execution paths.
- `REVIEWER_MODEL` may override the default model for the selected reviewer.
- If `REVIEWER_AGENT` is unset or `auto`:
  - Claude-family implementer: use `codex` with
    `REVIEWER_MODEL="${REVIEWER_MODEL:-gpt-5.6-sol}"` at high reasoning.
  - Codex/GPT-family implementer: use `claude` with
    `REVIEWER_MODEL="${REVIEWER_MODEL:-opus}"`.
- Every Claude-family review must use `claude-review-loop`. Do not invoke direct
  Claude plan mode, tool-disabled mode, tmux wrappers, or Bash-pattern
  allowlists. The dedicated harness owns isolation, exact context, structured
  output, lifecycle supervision, and fail-closed verdicts.
- Every Pi review must use `openai-codex/gpt-5.6-sol`. Never ask Pi to run a
  Claude/Anthropic model, a local model such as Qwen/Ollama/LM Studio, an
  OpenRouter model, or any other provider. Claude models run only through
  Claude Code and `claude-review-loop`.

Do not silently substitute a same-family reviewer. Honor an explicit user
choice without asking again. If the requested reviewer
command or model is unavailable, report the blocker. For Pi, fail closed if
the approved model or authentication is unavailable; never make an automatic
model, provider, or transport fallback.

Do not add `--max-budget-usd`, `--dangerously-skip-permissions`, or equivalent
ad hoc permission/budget flags to Claude review commands. Subscription usage
should not be represented as a per-run budget cap. Do not use write-capable
permission bypass for review.

## Model Roles And Cost

Choose a model per role, not per session. Spend where a wrong answer compounds -
the plan, and the first review verdict that gates the commit - and stay cheap
where the work is mechanical.

| Role | Default | Escalate a tier when |
|------|---------|----------------------|
| Orchestrator / plan | the session's own model | the design is genuinely open and a wrong shape costs a rewrite |
| Implementer | mid tier: `gpt-5.6-sol`, `sonnet`, or `opus` | two consecutive rounds produced no working repair and the failure is reasoning, not missing context |
| Reviewer, first round of a slice | `opus` (Claude) / `gpt-5.6-sol` (Codex, Pi) | not by default; this verdict already runs on the primary reviewer |
| Reviewer, delta re-review rounds | one tier below the primary reviewer is allowed | the round verifies a Critical repair, or the cheaper tier returns findings you cannot adjudicate |

`REVIEWER_MODEL` is read by this skill. `ORCHESTRATOR_MODEL`,
`IMPLEMENTER_MODEL`, and `REVIEWER_MODEL_DELTA` are conventions for the driving
agent to apply when it builds those commands; nothing reads them automatically.

Never default to the top tier. Claude Fable and GPT Astra are opt-in per run,
chosen deliberately and recorded - not the resting default for any role.

Reasoning effort is a separate axis from model choice, and it follows the model
generation rather than the price. Opus 5 and GPT-5.6 review at `high`, the newer
Astra generation at `medium`, and `xhigh` belongs to the Opus 4.x generation that
needed it. Do not raise effort merely because a model is expensive, and do not
let a request for a stronger model silently change effort as well.

A cheaper delta re-review is only safe on a round that is actually scoped -
`--baseline-ref` for Claude/Pi, an explicit delta prompt for Codex. Keep the
primary reviewer for any unscoped whole-slice round.

Record the model each role actually used, taken from the invocation. A
reviewer's self-reported identity inside its own report is not evidence of which
model ran.

## Cycle Continuation and Stopping Rule

Do not use a fixed numeric cap. A valid review is one that completed with a
parseable verdict from the selected reviewer; harness,
tooling, or lifecycle failures do not count. After every valid review,
adjudicate the findings and decide whether another fix/re-review cycle has
substantial expected value.

Retry an invalid review with a fresh run when practical. If the required
reviewer remains unavailable, stop and report the blocked review gate; absence
of findings from a failed attempt is not a clean result.

Continue when at least one of these applies:

- a Critical or Warning finding remains and an in-scope, practical repair is
  available;
- the review found a concrete correctness, safety, operator-workflow,
  requirements, regression, or documentation-sync risk;
- a repair materially changed the affected path and independent re-review would
  meaningfully reduce residual risk; or
- an aligned Suggestion identifies a plausible defect or missing regression
  whose repair value is material relative to its cost and churn.

Stop when any of these applies:

- the reviewer returns `CLEAN` and no accepted Critical or Warning from an
  earlier round remains unresolved;
- all remaining Suggestions are low-impact, speculative, stylistic, repetitive,
  out of scope, or explicitly deferred/rejected with concrete rationale;
- another cycle would mostly seek reviewer agreement rather than reduce a
  demonstrated risk;
- expected repair/review cost or churn exceeds the likely risk reduction; or
- progress is blocked by unavailable tooling, evidence, authorization, or an
  external dependency.

Apply these rules in this order:

1. An unresolved Critical or Warning never disappears because a narrower
   re-review is `CLEAN`.
2. When an in-scope practical repair exists and its expected risk reduction is
   substantial relative to its cost and churn, continue.
3. When a needed repair is blocked or no longer has substantial expected value,
   stop the loop, report the residual risk, and do not commit unless the commit
   gate below is satisfied. The agent cannot defer a blocked Critical on its own
   authority; a remaining Warning requires explicit user acceptance before
   commit.
4. After repairing an accepted Critical or Warning, continue for one independent
   re-review of that repair delta; the commit gate cannot be satisfied without
   it.
5. With no unresolved Critical or Warning, use all remaining continuation
   conditions, the Suggestion conditions, and diminishing returns to decide
   whether another cycle adds substantial value.

Cycle count is a diminishing-returns signal, not a stopping rule. As rounds
accumulate, require clearer evidence of incremental value. After each review,
record briefly why another cycle is justified or why the loop is stopping.

For Claude/Pi reviews, `--slice-id` computes two of these stopping conditions from
the recorded rounds - a required finding that survived two repairs, and a
Critical/Warning count that has not fallen across two consecutive rounds - and
returns exit `4` when either fires. Treat that as the loop ending: adjudicate
and report, rather than opening another round. Judgment still owns every other
condition here; the ledger only removes the ones that depend on remembering
earlier rounds.
Do not continue merely because the verdict is not `CLEAN`, and do not stop
merely because an arbitrary round count was reached.

### Re-review scope containment

The first valid review may inspect the complete implementation slice. After
that review, freeze its accepted findings as the repair baseline.

For a Claude/Pi re-review, scope the bundle itself with `--baseline-ref` (see the
reviewer procedure above) rather than relying on the prompt alone. For Codex,
say the scope in the prompt and quote only the accepted findings.

For every re-review:

- ask the reviewer to verify the accepted prior findings and the repair delta,
  not to restart an unrestricted whole-slice audit, unless the repair itself had
  broad, cross-cutting impact and the driver recorded why reopening the whole
  slice is necessary;
- classify each new finding as caused by the repair, directly coupled to the
  repaired path, or pre-existing/unrelated to that delta;
- expand the current gate for every Critical, for every Critical or Warning
  caused by or directly coupled to the repair, or when the finding directly
  invalidates the original acceptance criteria, safety boundary, persisted
  evidence, or claimed fix;
- record other pre-existing or unrelated findings as follow-up work instead of
  repairing them recursively in the current loop. A deferred Warning still
  requires explicit user acceptance before commit, and a Critical cannot be
  deferred this way; and
- stop broad re-review if successive rounds keep discovering unrelated concerns
  rather than regressions from the latest repair.

A targeted loop has converged when every item in the current gate — the frozen
baseline plus any permitted expansions — is resolved and the repair delta
introduces no Critical or Warning regression. It does not need to eliminate
every concern that a fresh whole-slice audit could discover.

## Commit Gate

Commit only when:

- at least one valid review from the selected reviewer completed and its findings were
  adjudicated, and
- no Critical or Warning findings remain, and
- Suggestions are fixed, explicitly deferred with rationale, or rejected with
  rationale, and
- required checks and docs are complete.

If substantial review value is exhausted while Critical or Warning findings
remain, stop, report the residual risk, and do not commit without explicit user
direction. The agent may never defer or accept a Critical on its own authority;
only an explicit user override can release that gate.

## Supervising A Noninteractive Implementer

The review harnesses supervise the reviewer. Nothing supervises an implementer
driven noninteractively in the same loop, so it needs its own guard.

- Wrap every noninteractive implementer invocation in `timeout` with a hard cap.
  Never rely on a foreground command cap as the stall detector: moving the call
  to a background job silently removes it.
- Supervise progress by observed work — new or modified files — not by process
  liveness. A wedged agent keeps its process, so `pgrep` succeeding is not
  evidence of progress. An observed hang produced an empty log and zero file
  writes for about eight hours while liveness checks kept passing.
- Treat "no output and no file writes" as failure, and say so, rather than
  reporting the slice as still in flight.
- This is the same failure family as the empty-log wrapper hangs already
  recorded for the Pi review branch below; both paths need a bounded wait.

`pi --print` sometimes never exits, and its wrapper outlives it. Because Pi
buffers its summary until the end, the log stays empty either way — so an empty
log distinguishes nothing on its own. Observed three times: once before any work
was done, and once after the implementation, tests, and docs were all written
correctly and it hung only at exit.

- The working tree is the evidence, not the report. Adjudicate a missing report
  by inspecting what is actually on disk.
- A missing report means the slice is unverified, not that it is finished and
  not that it is empty. Read the diff yourself and re-run the verification
  before the review gate, then use a fresh bounded session only for whatever is
  genuinely missing.
- Independently re-run the implementer's claimed verification even when a report
  does arrive. Reports of green suites have proven wrong in practice.
- Verify a claimed edit in the code, not in the report. A worker reported making
  a parameter required while the saved signature still had it optional, and the
  claim survived into the review prompt.
- With several workers on one slice, stop them all and let their edits settle
  before collecting the check you will quote as evidence. Edits landing during
  collection produced stale assertions describing neither the old tree nor the
  new one.
- When a worker edits tests, compare what each assertion can still detect rather
  than whether the suite still passes. A whole-map emptiness check replaced by a
  single-key absence check is strictly weaker and reads as an ordinary refactor
  in the diff.
- Kill the orphan before starting anything else.

## Reviewer Procedure

1. Resolve the reviewer branch first. For Pi, use its harness in step 3; no
   sentinel or hand-written prompt is needed. For Codex, generate the run's nonce
   before anything else, because the prompt and the poll loop must both use this
   one value:

   ```bash
   nonce="$(openssl rand -hex 8)"
   ```

   Then build the matching prompt described in
   **Review Prompt Contents** below, asking for `=== REVIEW COMPLETE $nonce ===`
   as its final line. For Claude, `$review_prompt` must contain
   only the narrow trusted-context subset. For Codex, it must contain the full
   review directives and output contract. Only then write that branch-specific
   body to a temp file:

   ```bash
   prompt_file="$(mktemp -t review-prompt.XXXXXX)"
   printf '%s' "$review_prompt" > "$prompt_file"
   ```

2. For `claude` (including both legacy aliases), run the dedicated harness in
   the foreground. Do not wrap it in tmux or poll it. The review context is
   copied into the exact, redacted bundle artifact:

   ```bash
   reviewer_model="${REVIEWER_MODEL:-opus}"
   run_dir="$(mktemp -d -t claude-review.XXXXXX)"
   slice_id="${SLICE_ID:-$(basename "$PWD")-$(git rev-parse --short HEAD 2>/dev/null || echo no-head)}"
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" \
     --run-dir "$run_dir" \
     --model "$reviewer_model" \
     --context-file "$prompt_file" \
     --slice-id "$slice_id" \
     --record-baseline
   ```

   `--slice-id` is any stable name for this slice, reused for every round. The
   default keys on the current commit rather than the branch: review rounds do
   not commit, so it holds across a slice, and it changes once you commit and
   start the next one. A branch name would not - every slice on a long-lived
   branch would inherit the previous slice's rounds and could hit exit `4` on
   its first round. Name the slice explicitly with `SLICE_ID` when a slice does
   span commits. The
   harness then keeps a cross-round ledger and reports whether the loop is
   converging, so the stopping conditions below are computed from the actual
   round history rather than from what this session still remembers of it.

   For a delta round you may drop one reviewer tier with
   `reviewer_model="${REVIEWER_MODEL_DELTA:-$reviewer_model}"` - see
   **Model Roles And Cost**, and keep the primary reviewer when the round
   verifies a Critical repair.

   `--record-baseline` reports a `baseline_commit` in `result.json`. Pass it to
   the next round as `--baseline-ref "$baseline_commit"` — with
   `--record-baseline` again — so the re-review bundle holds only the repair
   delta. This is how **Re-review scope containment** below is actually
   enforced: without it every round re-sends the whole slice and the reviewer
   keeps finding new unrelated concerns in code it already passed.

   Interpret exit `0` as clean, `1` as findings, `2` as a failed/invalid review,
   `3` as lock contention, and `4` as findings plus a ledger verdict that the
   loop is not converging - stop, report the residual risk, and do not start
   another round on your own authority. Exit `4` never means the findings are
   resolved. Read `$run_dir/result.json` when it exists; a
   scoped clean result still requires explicit judgment about skips, truncations,
   or redactions. A non-empty-run-directory rejection (exit `2`) and lock
   contention (exit `3`) happen before the reviewer runs and do not create a new
   result; do not mistake a pre-existing stale result in that directory for the
   current attempt. Create a fresh `run_dir` for every attempt, including retries
   after exits `1`, `2`, or `3`; never retry the same command with a populated
   artifact directory.
   Preserve the harness defaults unless the user requested a model/effort change.

3. For `pi`, use the existing [pi-review-loop](../../../claude/skills/pi-review-loop/SKILL.md)
   harness in the foreground. Resolve this relative link against the real skill
   source directory when this skill is installed through a symlink. Read that
   skill before invoking its harness; do not recreate its preflight or lifecycle
   in a tmux script.

   ```bash
   python3 ~/projects/agent-stuff/claude/skills/pi-review-loop/bin/pi-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/pi-review" \
     --model openai-codex/gpt-5.6-sol
   ```

   Pi uses the shared redacted bundle, no repository tools, and structured
   results. Use its `--record-baseline`, `--baseline-ref`, `--slice-id`, and
   manifest checks for the same repair containment as Claude. Baseline snapshots
   are optional when Git object storage is read-only; a first full review does
   not require them. For subsequent repair reviews, prepare a scoped reviewable
   checkout in a writable workspace if needed and preserve the reviewed state.
   The harness owns timeouts, model preflight, retries, and child cleanup. Do not
   use direct `pi -p`, sentinel polling, or an alternative provider as a fallback.

   Both authentication and model discovery need Pi's normal local state access,
   even though the reviewer has no tools. The default state directory is
   `~/.pi/agent`; the harness supports a deliberate `PI_REVIEW_AGENT_DIR` override
   and ignores ambient `PI_CODING_AGENT_DIR`. Use an override only for an existing,
   deliberately selected Pi profile. Do not copy credentials to scratch storage
   or disable authentication locks to work around a sandbox denial.

   Classify failures from their actual cause:

   - `EPERM`/`EACCES` creating `auth.json.lock` or `settings.json.lock` means local
     state access is blocked. Authentication and model availability are still
     untested; do not describe the account as logged out or recommend login.
   - A provider DNS/connection failure is a network failure, not a code finding.
   - A completed listing without the approved model is a model-availability
     failure. Only an actual authentication failure warrants authentication repair.

   Fix in-scope invocation errors and retry once in a fresh directory when the
   cause has changed. If execution permissions are the barrier, use an escalation
   only when the active tool policy permits it. With approvals disabled, give the
   exact prepared command and required access for a later permitted run; do not
   invent a permission question or repeat an unchanged failing call. A failed
   invocation is not a review result. These environment limitations are not
   caused by the skill's review gate.

   For `codex` only, use tmux with a read-only review command. Generate the nonce
   and full prompt from step 1. Write a runner using a quoted heredoc:

   ```bash
   session="review-$(basename "$PWD")-$(date +%Y%m%d%H%M%S)"
   log_file="/tmp/${session}.out"
   runner_file="$(mktemp -t review-run.XXXXXX.fish)"
   reviewer_model="${REVIEWER_MODEL:-gpt-5.6-sol}"
   cat > "$runner_file" <<'FISH'
   set prompt_file $argv[1]
   set log_file $argv[2]
   set reviewer_model $argv[3]
   set reasoning_effort high
   if string match -q '*astra*' -- "$reviewer_model"
       set reasoning_effort medium
   end
   codex -a never exec --sandbox read-only -m "$reviewer_model" \
     -c "model_reasoning_effort=\"$reasoning_effort\"" - < "$prompt_file" 2>&1 | tee "$log_file"
   set statuses $pipestatus
   printf "\n[review pipeline statuses: %s]\n" "$statuses" | tee -a "$log_file"
   read -P "review finished; press Enter to close tmux pane"
   FISH
   tmux new-session -d -s "$session" -c "$PWD" \
     "fish \"$runner_file\" \"$prompt_file\" \"$log_file\" \"$reviewer_model\""
   ```

4. For the Codex tmux branch only, poll the log file until the reviewer
   prints the required completion sentinel. `codex exec` echoes the full prompt
   into the log before running, so the sentinel appears once as prompt text.
   Require at least two matches; a prompt echo is not a completed review.

   Counting a fixed sentinel is only safe while the reviewed code cannot contain
   it. Reviewing these skills breaks that: their own docs quote the sentinel and
   the runner, the reviewer echoes the files it reads, and the count reaches the
   threshold mid-review. Generate a per-run nonce instead - `nonce=$(openssl
   rand -hex 8)`, ask for `=== REVIEW COMPLETE $nonce ===`, and poll for that;
   nothing already in the repository can contain it. Falling back on the tmux
   session ending does not help either when the runner deliberately holds the
   pane open; wait on the reviewer process when in doubt.

   The nonce makes the count
   trustworthy; without it the threshold is guesswork. Use the `$nonce` from
   step 1 - the one already embedded in the prompt. Generating a fresh one here
   would grep for a sentinel the reviewer was never asked to print, and the loop
   would time out on a review that had finished.

   ```bash
   # $nonce is the value generated before the prompt was written, and the
   # prompt asked for `=== REVIEW COMPLETE $nonce ===` as its final line.
   completed=0
   for _ in $(seq 1 180); do
       if [ -f "$log_file" ] && [ "$(grep -Fc "=== REVIEW COMPLETE $nonce ===" "$log_file")" -ge 2 ]; then
           tail -200 "$log_file"
           completed=1
           break
       fi
       if ! tmux has-session -t "$session" 2>/dev/null; then
           echo "Review tmux session ended before emitting completion sentinel." >&2
           [ -f "$log_file" ] && tail -200 "$log_file"
           exit 1
       fi
       sleep 10
   done
   if [ "$completed" -ne 1 ]; then
       echo "Review did not emit completion sentinel; inspect the tmux session and $log_file." >&2
       exit 1
   fi
   ```

5. When the review is complete, keep the session available until the cycle is
   resolved. Kill only when the report has been captured or summarized:

   ```bash
   tmux kill-session -t "$session"
   ```

   After any manual stop or tmux kill, verify that no Codex reviewer child
   remains. Tmux can exit while its child process continues; terminate the
   surviving reviewer process group before starting another cycle.

   Claude/Pi lifecycle cleanup belongs to their respective harnesses; do not
   recreate it with tmux polling.

## Wrapper Shell Hazards

Both of these have recurred after being recorded once, so treat them as rules
rather than trivia.

- Never name a wrapper variable `status`. It is read-only in zsh and the
  assignment fails. Use `review_exit`.
- Quote literal search patterns in single quotes. A pattern copied from
  Markdown carries backticks, and inside double quotes the shell runs them as
  command substitution — this started a full iOS test suite twice during
  closeout checks and destroyed an in-progress result bundle both times. The
  same applies to heredocs used to build prompts: quote the delimiter
  (`<<'EOF'`) whenever the body contains a backtick **at all**, not merely a
  code fence. One backticked identifier is enough, and that is the likeliest
  form in a review prompt — naming the function under review. An unquoted
  delimiter runs it, silently corrupting the prompt, and the review then starts
  against text you did not write. When the body must also interpolate a path,
  write the file from a quoted heredoc using a placeholder and substitute it
  afterwards rather than reaching for an unquoted delimiter.

Build prompts and runners as files with arguments passed positionally. Nested
quoting inside a single `tmux new-session` string has repeatedly expanded in the
outer shell before tmux started, producing a pane that exits before the reviewer
launches.

## Review Prompt Contents

For Claude, `--context-file` is a trusted caller-authored region. Include only:

- review round label
- your own implementation intent, scope, requirements, and non-goals
- paths to relevant caller-selected specs or docs
- your own verification-command/result summaries
- prior findings restated as concise caller-authored verification goals

Never paste raw diffs, repository text/status output, or verbatim prior reviewer
output into Claude context. Do not add severity, read-only, tool, or output-format
directives; the harness system instruction and JSON schema own those policies.
The harness supplies repository evidence separately after the untrusted boundary.

For Codex tmux prompts, say this is review rather than implementation and
include:

- review round number and whether it is a first review or re-review
- implementation intent and scope
- relevant project instructions, specs, docs, or backlog item paths
- touched files and what changed, including untracked files from
  `git status --short --untracked-files=all`
- verification commands already run and results
- known trade-offs or explicit non-goals
- prior findings and how they were addressed for re-reviews
- for a re-review, the explicit scope boundary: verify only the accepted prior
  findings and the repair delta unless the repair had broad, cross-cutting
  impact whose recorded rationale requires reopening the whole slice
- when preparing Codex re-reviews, strip a quoted prior report's trailing
  completion sentinel before adding it to the prompt
- severity policy: Critical, Warning, Suggestion
- instruction to verify docs/release notes when behavior or workflow changed
- explicit instruction that this is read-only review: the reviewer must not
  edit files, stage changes, commit, or otherwise mutate the worktree
- output contract with findings first and summary-safe metrics; the final line
  must be exactly `=== REVIEW COMPLETE <nonce> ===`, using the per-run nonce
  from the reviewer procedure. A fixed sentinel is unreliable: the reviewer
  echoes the files it reads, so any repository that documents the sentinel puts
  extra copies in the log and ends the poll mid-review.

For Codex, ask the reviewer to report:

- finding counts by severity for this round
- accepted, fixed, rejected, and deferred finding counts when known
- whether the cycle can close
- reviewer agent/model and implementer agent/model
- whether subagents materially affected the review

For Claude/Pi, do not add these fields to the strict review schema. Derive finding
counts, cycle status, and tool/delegation evidence from `result.json`; track
accepted/fixed/rejected/deferred counts in the driving agent's cycle summary.

## Handling Findings

- Critical: fix before commit unless the user explicitly changes scope.
- Warning: fix before commit, or ask the user before accepting the risk.
- Suggestion: fix when low-cost and aligned; otherwise defer or reject with a
  concrete rationale.
- For re-review, verify only the accepted prior findings plus the repair delta.
  Reopen the whole slice only when the repair itself had broad, cross-cutting
  impact, and record why that expansion is necessary.

### Judging a finding

A reviewer is a source of claims, not verdicts you owe agreement to.

- Disprove a false finding with evidence rather than editing around it. Execute
  the failure it claims before accepting it: reviewers have reported a check-mode
  failure that does not occur, and read a slash-containing branch name as a
  missing path. Record the evidence and reject the finding.
- Give a small-delta review the unchanged context it needs. A reviewer shown
  only an incremental diff has inferred a bypass that the unchanged guard
  directly above it prevents. State those invariants in the review context
  rather than letting the reviewer guess from the delta.
- Qualify a reviewer-proposed invariant before promoting it into a plan or a
  docstring. Trace the whole admission and retirement path first: adopted
  cardinality and epoch wording has overgeneralized real behavior, because a
  global key can bypass a scoped counter and shutdown can intentionally skip
  ordinary outcome recording.
- Do not let a prerequisite you invented become a user-authorization barrier. An
  overbuilt rescue-console step for a proxy-only patch was rejected by the owner;
  the routine patch needed truthful recovery evidence, not a new gate.

### Judging the evidence a repair offers

- Drive an error-boundary regression through the production caller chain. A
  helper-only test passes even when production stops calling the helper, and an
  outer envelope that catches `TypeError` can downgrade a configuration failure
  to a 400 without any helper test noticing.
- A new regression that also passes against the pre-repair code is
  behavioral-preservation evidence, not a reproduction. Run it against the old
  code and require it to fail; assert that an injected fault actually executed,
  since a rollback test returning False can pass before its failure runs.
- When successive rounds keep finding *new* defects in one component rather than
  narrowing on one argument, the design is the finding. Three rounds once spent
  their Criticals on a hand-rolled encoder for git tree entries - submodules,
  unreadable paths, alternate indexes - each repair introducing the next defect.
  The fix was not a fourth round but letting git build the tree. Stop and put
  that choice to the operator instead of buying another round.
- Review a repair delta as its own change, not as a smaller version of a
  reviewed one. In one observed cycle every Critical in round 2 was introduced
  by round 1's repairs: the fix for a secret-exposure warning wrote a raw
  credential into a snapshot, and the fix for one silent omission created
  another. A repair is written under time pressure against a narrowed view,
  which is exactly where the last review's blind spot lives.
- Update the backlog or work item as soon as implementation validation passes,
  not after the review. A review round spent reporting that the backlog still
  describes fixed findings as future work is a round bought for nothing.

## Learning Logs

After each review cycle or unexpected workflow failure, record summary-safe
lessons when the goal prompt, review loop, validation, model pairing, tmux
orchestration, or backlog shape did not work as expected.

- Reusable agent/process lessons go in:
  `~/projects/agent-stuff/docs/review-cycle-log.md`
- Project-specific execution lessons go in that project's own workflow log
  when one exists, for example:
  `docs/workflow/lessons.md`

Use short entries with expected behavior, actual behavior, impact, fix or
follow-up, and status. Do not include raw prompts, transcripts, secrets,
credentials, large tool output, or per-run metrics: a line of test counts and
durations records what one run measured, not what the next run should do
differently.

End every entry with a `Promotion:` line, and close the cycle by acting on it -
either promote the lesson into the skill it affects and mark it
`promoted - <skill>, <section>`, or decide it earns no rule and mark it
`incident`. `pending` is for a lesson whose change you cannot make right now,
not a default. A log of lessons nobody promoted is how the review skills drifted
into contradicting each other for six weeks.

Record the review outcome in the final commit-ready summary.
