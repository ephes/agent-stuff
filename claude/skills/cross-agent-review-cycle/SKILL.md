---
name: cross-agent-review-cycle
description: Use before committing an implementation slice when a configurable different-family reviewer should inspect the slice, or when coordinating up to three fix/re-review cycles with Claude, Codex, or Pi. Claude reviews delegate to the supervised claude-review-loop harness.
---

# Cross-Agent Review Cycle

## Purpose

Run a bounded independent review loop before committing an implementation
slice. The reviewer must be a different model family from the implementer.

## Reviewer Selection

- The reviewer must be a different model family from the implementer.
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

Do not silently substitute a same-family reviewer. If the requested reviewer
command or model is unavailable, report the blocker. For Pi, fail closed if
the approved model or authentication is unavailable; never make an automatic
model, provider, or transport fallback.

Do not add `--max-budget-usd`, `--dangerously-skip-permissions`, or equivalent
ad hoc permission/budget flags to Claude review commands. Subscription usage
should not be represented as a per-run budget cap. Do not use write-capable
permission bypass for review.

## Cycle Limit

Run at most three review cycles for a single implementation slice.

- Cycle 1: first review of the completed slice.
- Cycle 2: re-review after fixes or explicit decisions.
- Cycle 3: final re-review if cycle 2 still found issues that were fixed or
  need closure.

Commit only when:

- no Critical or Warning findings remain, and
- Suggestions are fixed, explicitly deferred with rationale, or rejected with
  rationale, and
- required checks and docs are complete.

If Critical or Warning findings remain after three cycles, do not commit
without explicit user direction.

## Reviewer Procedure

1. Resolve the reviewer branch first, then build the matching prompt described in
   **Review Prompt Contents** below. For Claude, `$review_prompt` must contain
   only the narrow trusted-context subset. For Codex/Pi, it must contain the full
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
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" \
     --run-dir "$run_dir" \
     --model "$reviewer_model" \
     --context-file "$prompt_file"
   ```

   Interpret exit `0` as clean, `1` as findings, `2` as a failed/invalid review,
   and `3` as lock contention. Read `$run_dir/result.json` when it exists; a
   scoped clean result still requires explicit judgment about skips, truncations,
   or redactions. A non-empty-run-directory rejection (exit `2`) and lock
   contention (exit `3`) happen before the reviewer runs and do not create a new
   result; do not mistake a pre-existing stale result in that directory for the
   current attempt. Create a fresh `run_dir` for every attempt, including retries
   after exits `1`, `2`, or `3`; never retry the same command with a populated
   artifact directory.
   Preserve the harness defaults unless the user requested a model/effort change.

3. For `codex` or `pi`, use the tmux procedure below. Choose stable paths:

   ```bash
   session="review-$(basename "$PWD")-$(date +%Y%m%d%H%M%S)"
   log_file="/tmp/${session}.out"
   runner_file="$(mktemp -t review-run.XXXXXX.fish)"
   reviewer_agent="${REVIEWER_AGENT:?set REVIEWER_AGENT to the already-resolved codex or pi branch}"
   reviewer_model="${REVIEWER_MODEL:-}"
   cat > "$runner_file" <<'FISH'
   set prompt_file $argv[1]
   set log_file $argv[2]
   set reviewer_agent $argv[3]
   set reviewer_model $argv[4]
   if test "$reviewer_agent" = auto
       echo "auto must be resolved by the caller before the tmux-only runner" | tee "$log_file"
       exit 64
   end
   switch "$reviewer_agent"
       case codex
           test -n "$reviewer_model"; or set reviewer_model gpt-5.6-sol
           codex -a never exec --sandbox read-only -m "$reviewer_model" \
             -c 'model_reasoning_effort="high"' - < "$prompt_file" 2>&1 | tee "$log_file"
       case pi
           test -n "$reviewer_model"; or set reviewer_model openai-codex/gpt-5.6-sol
           set reviewer_model_lookup (string replace -r ':(off|minimal|low|medium|high|xhigh|max)$' '' -- "$reviewer_model")
           if test "$reviewer_model_lookup" != openai-codex/gpt-5.6-sol
               echo "unsupported Pi review model: $reviewer_model; mandatory Pi reviews use openai-codex/gpt-5.6-sol only (no Claude/Anthropic, local models, OpenRouter, or provider fallback)" | tee "$log_file"
               exit 64
           end
           if not command -q pi
               echo "pi reviewer unavailable: pi command not found on PATH" | tee "$log_file"
               exit 127
           end
           set pi_models (env PI_TELEMETRY=0 pi --list-models gpt 2>&1 | string collect)
           set pi_models_status $pipestatus[1]
           if test $pi_models_status -ne 0
               echo "pi reviewer unavailable in this environment; direct pi may still work in another shell if that shell has provider auth" | tee "$log_file"
               printf "%s\n" "$pi_models" | tee -a "$log_file"
               exit 69
           end
           if string match -q '*No models matching*' -- "$pi_models"; or string match -q '*No models available*' -- "$pi_models"; or string match -q '*No API key found*' -- "$pi_models"
               if string match -q '*No models available*' -- "$pi_models"; or string match -q '*No API key found*' -- "$pi_models"
                   echo "pi reviewer unavailable in this environment; direct pi may still work in another shell if that shell has provider auth" | tee "$log_file"
               else
                   echo "pi reviewer unavailable: requested model $reviewer_model is not listed by pi in this environment" | tee "$log_file"
               end
               printf "%s\n" "$pi_models" | tee -a "$log_file"
               exit 69
           end
           if not string match -rq 'openai-codex[ /]+gpt-5\.6-sol' -- "$pi_models"
               echo "pi reviewer unavailable: required model openai-codex/gpt-5.6-sol is not listed by pi in this environment" | tee "$log_file"
               printf "%s\n" "$pi_models" | tee -a "$log_file"
               exit 69
           end
           set reviewer_model "$reviewer_model_lookup"
           env PI_TELEMETRY=0 pi -p --no-session --no-context-files --approve \
             --model "$reviewer_model" --thinking high \
             --tools read,grep,find,ls @"$prompt_file" > "$log_file" 2>&1
       case '*'
           echo "unsupported REVIEWER_AGENT=$reviewer_agent" | tee "$log_file"
           exit 64
   end
   set statuses $pipestatus
   printf "\n[review pipeline statuses: %s]\n" "$statuses" | tee -a "$log_file"
   read -P "review finished; press Enter to close tmux pane"
   FISH
   tmux new-session -d -s "$session" -c "$PWD" \
     "fish \"$runner_file\" \"$prompt_file\" \"$log_file\" \"$reviewer_agent\" \"$reviewer_model\""
   ```

   For a Claude implementer, resolve `REVIEWER_AGENT=codex` unless another
   different-family reviewer was explicitly requested. If no stable
   noninteractive command is available for the requested reviewer, fall back to
   an interactive tmux session only after telling the user.

   The Pi branch deliberately uses `@"$prompt_file"` with direct log
   redirection. Do not replace it with a positional prompt, stdin, or a `tee`
   pipeline; those forms have produced empty-log wrapper hangs in observed runs.

   The Pi branch rejects every model except `openai-codex/gpt-5.6-sol`, then
   preflights that exact model before starting the review.
   Exit `64` means the caller requested a forbidden Pi review model, exit `127`
   means `pi` was not on PATH, and exit `69` means this environment could not
   list the authenticated approved model. Report that blocker instead of
   treating the review as queued or clean.

4. For the Codex/Pi tmux branches only, poll the log file until the reviewer
   prints the required completion sentinel. With one-shot `-p`, the prompt is
   not echoed, so one sentinel match is enough.

   ```bash
   completed=0
   for _ in $(seq 1 180); do
       if [ -f "$log_file" ] && grep -Fq '=== REVIEW COMPLETE ===' "$log_file"; then
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

   After any manual stop or tmux kill, verify that no Codex/Pi reviewer child
   remains. Tmux can exit while its child process continues; terminate the
   surviving reviewer process group before starting another cycle.

   Claude lifecycle cleanup belongs exclusively to `claude-review-loop`; do not
   recreate it with tmux polling.

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

For Codex/Pi tmux prompts, say this is review rather than implementation and
include:

- review round number and whether it is first review, re-review, or final
  allowed review
- implementation intent and scope
- relevant project instructions, specs, docs, or backlog item paths
- touched files and what changed
- verification commands already run and results
- known trade-offs or explicit non-goals
- prior findings and how they were addressed for re-reviews
- when preparing Codex/Pi re-reviews, strip a quoted prior report's trailing
  `=== REVIEW COMPLETE ===` sentinel before adding them to the prompt
- severity policy: Critical, Warning, Suggestion
- instruction to verify docs/release notes when behavior or workflow changed
- explicit instruction that this is read-only review: the reviewer must not
  edit files, stage changes, commit, or otherwise mutate the worktree
- output contract with findings first and summary-safe metrics; the final line
  must be exactly `=== REVIEW COMPLETE ===`.

For Codex/Pi, ask the reviewer to report:

- finding counts by severity for this round
- accepted, fixed, rejected, and deferred finding counts when known
- whether the cycle can close
- reviewer agent/model and implementer agent/model
- whether subagents materially affected the review

For Claude, do not add these fields to the strict review schema. Derive finding
counts, cycle status, and tool/delegation evidence from `result.json`; track
accepted/fixed/rejected/deferred counts in the driving agent's cycle summary.

## Handling Findings

- Critical: fix before commit unless the user explicitly changes scope.
- Warning: fix before commit, or ask the user before accepting the risk.
- Suggestion: fix when low-cost and aligned; otherwise defer or reject with a
  concrete rationale.
- For re-review, ask the reviewer to verify only prior findings plus changed
  scope unless the fixes had broad impact.

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
credentials, or large tool output.

Record the review outcome in the final commit-ready summary.
