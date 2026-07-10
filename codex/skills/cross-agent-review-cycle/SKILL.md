---
name: cross-agent-review-cycle
description: Use before committing an implementation slice when the project requires an external tmux review loop, especially when a configurable different-family reviewer should inspect the slice, or when coordinating up to three fix/re-review cycles with Claude, Codex, or Pi.
---

# Cross-Agent Review Cycle

## Purpose

Run a bounded independent review loop before committing an implementation
slice. The reviewer must be a different model family from the implementer.

## Reviewer Selection

- The reviewer must be a different model family from the implementer.
- `REVIEWER_AGENT` may override the default reviewer. Supported values:
  `auto`, `claude-plan`, `claude-no-tools`, `codex`, and `pi`.
- `REVIEWER_MODEL` may override the default model for the selected reviewer.
- If `REVIEWER_AGENT` is unset or `auto`:
  - Codex/GPT-family implementer: use `claude-plan` with
    `REVIEWER_MODEL="${REVIEWER_MODEL:-opus}"`.
  - Claude-family implementer: use `codex` with
    `REVIEWER_MODEL="${REVIEWER_MODEL:-gpt-5.6-sol}"` at high reasoning.
- Prefer `claude-plan` over `claude-no-tools` when the reviewer needs to inspect
  the worktree. Repeated failures show that fully tool-disabled Claude reviews
  can exit with no sentinel, try unavailable tools, or hallucinate verification.

Do not silently substitute a same-family reviewer. If the requested reviewer
command or model is unavailable, report the blocker.

Do not add `--max-budget-usd`, `--dangerously-skip-permissions`, or equivalent
ad hoc permission/budget flags to Claude review commands. Subscription usage
should not be represented as a per-run budget cap. For Claude reviews, use
either `claude-plan` with a read-only allowlist or `claude-no-tools` with a
self-contained prompt; do not use write-capable permission bypass for review.

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

## tmux Procedure

1. Choose a stable session name:

   ```bash
   session="review-$(basename "$PWD")-$(date +%Y%m%d%H%M%S)"
   ```

2. Write the self-contained review prompt to a temp file and choose a log path:

   ```bash
   prompt_file="$(mktemp -t review-prompt.XXXXXX)"
   log_file="/tmp/${session}.out"
   printf '%s' "$review_prompt" > "$prompt_file"
   ```

3. Run the selected reviewer as a one-shot noninteractive review inside tmux.
   Feed or pass the prompt as one intact value and tee the log for inspection:

   ```bash
   runner_file="$(mktemp -t review-run.XXXXXX.fish)"
   cat > "$runner_file" <<'FISH'
   set prompt_file $argv[1]
   set log_file $argv[2]
   set reviewer_agent (set -q REVIEWER_AGENT; and echo $REVIEWER_AGENT; or echo auto)
   set reviewer_model (set -q REVIEWER_MODEL; and echo $REVIEWER_MODEL; or echo "")
   if test "$reviewer_agent" = auto
       set reviewer_agent claude-plan
   end
   switch "$reviewer_agent"
       case claude-plan
           test -n "$reviewer_model"; or set reviewer_model opus
           claude -p --model "$reviewer_model" --no-session-persistence \
             --permission-mode plan \
             --allowedTools "Read,Grep,Glob,Bash(git diff *),Bash(git status *),Bash(rg *),Bash(grep *),Bash(ls *)" \
             --disallowedTools "Edit,Write" \
             --disable-slash-commands < "$prompt_file" 2>&1 | tee "$log_file"
       case claude-no-tools
           test -n "$reviewer_model"; or set reviewer_model opus
           claude -p --model "$reviewer_model" --no-session-persistence \
             --tools "" --disable-slash-commands < "$prompt_file" 2>&1 | tee "$log_file"
       case codex
           test -n "$reviewer_model"; or set reviewer_model gpt-5.6-sol
           codex -a never exec --sandbox read-only -m "$reviewer_model" \
             -c 'model_reasoning_effort="high"' - < "$prompt_file" 2>&1 | tee "$log_file"
       case pi
           test -n "$reviewer_model"; or set reviewer_model openai-codex/gpt-5.6-sol
           if not command -q pi
               echo "pi reviewer unavailable: pi command not found on PATH" | tee "$log_file"
               exit 127
           end
           set reviewer_model_lookup (string replace -r ':(off|minimal|low|medium|high|xhigh|max)$' '' -- "$reviewer_model")
           set pi_models (env PI_TELEMETRY=0 pi --list-models "$reviewer_model_lookup" 2>&1 | string collect)
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
           set reviewer_model "$reviewer_model_lookup"
           set prompt_text (cat "$prompt_file" | string collect)
           env PI_TELEMETRY=0 pi -p --no-session --no-context-files --approve \
             --model "$reviewer_model" --thinking high \
             --tools read,grep,find,ls "$prompt_text" 2>&1 | tee "$log_file"
       case '*'
           echo "unsupported REVIEWER_AGENT=$reviewer_agent" | tee "$log_file"
           exit 64
   end
   set statuses $pipestatus
   printf "\n[review pipeline statuses: %s]\n" "$statuses" | tee -a "$log_file"
   read -P "review finished; press Enter to close tmux pane"
   FISH
   tmux new-session -d -s "$session" -c "$PWD" \
     "fish \"$runner_file\" \"$prompt_file\" \"$log_file\""
   ```

   For a Claude implementer, set `REVIEWER_AGENT=codex` unless another
   different-family reviewer was explicitly requested. If no stable
   noninteractive command is available for the requested reviewer, fall back to
   an interactive tmux session only after telling the user.

   The Pi branch preflights `pi --list-models gpt` before starting the review.
   Exit `127` means `pi` was not on PATH; exit `69` means this environment could
   not list an authenticated GPT model. Report that blocker instead of treating
   the review as queued or clean.

4. Poll the log file until the reviewer prints the required completion sentinel.
   With one-shot `-p`, the prompt is not echoed, so one sentinel match is enough.
   The log may stay empty while Claude is still thinking; treat that as normal
   until the session exits or the polling deadline expires.

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

   If you manually stop or kill a tmux review before completion, verify that no
   `claude --model opus` child remains. Kill the review process group before
   starting another review; tmux can exit while the Claude child continues
   running.

## Claude Prompt Discipline

- Prompt via stdin: use exactly one stdin source, such as `< "$prompt_file"`;
  do not also pass a positional prompt.
- Prompt as an argument: put it after `--` and close stdin, for example
  `claude -p --model opus --no-session-persistence --tools "" --disable-slash-commands -- "$PROMPT" </dev/null`.
- `--tools ""` is variadic. Never put a positional prompt immediately after it;
  either use stdin or insert `--` before the prompt.
- Use `claude-no-tools` only when the prompt embeds the exact diff/evidence and
  tells Claude to state limitations instead of inventing file reads. Use
  `claude-plan` for normal code reviews that need direct worktree inspection.

## Review Prompt Contents

The prompt must say this is a review task, not implementation. Include:

- review round number and whether it is first review, re-review, or final
  allowed review
- implementation intent and scope
- relevant project instructions, specs, docs, or backlog item paths
- touched files and what changed, including untracked files from
  `git status --short --untracked-files=all`
- verification commands already run and results
- known trade-offs or explicit non-goals
- prior findings and how they were addressed for re-reviews
- if quoting prior review reports, strip their trailing
  `=== REVIEW COMPLETE ===` sentinel before adding them to the prompt
- severity policy: Critical, Warning, Suggestion
- instruction to verify docs/release notes when behavior or workflow changed
- explicit instruction that this is read-only review: the reviewer must not
  edit files, stage changes, commit, or otherwise mutate the worktree
- output contract with findings first and summary-safe metrics
- final line must be exactly `=== REVIEW COMPLETE ===`

Ask the reviewer to report:

- finding counts by severity for this round
- accepted, fixed, rejected, and deferred finding counts when known
- whether the cycle can close
- reviewer agent/model and implementer agent/model
- whether subagents materially affected the review

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
