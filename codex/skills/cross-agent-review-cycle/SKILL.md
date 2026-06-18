---
name: cross-agent-review-cycle
description: Use before committing an implementation slice when the project requires an external tmux review loop, especially when Codex implemented the slice and Claude should review it, or when coordinating up to three fix/re-review cycles with claude-yolo or codex-yolo.
---

# Cross-Agent Review Cycle

## Purpose

Run a bounded independent review loop before committing an implementation
slice. The reviewer must be a different model family from the implementer.

## Reviewer Selection

- If the implementer is Codex, review with Claude:
  `claude-yolo -p --model opus`
- If the implementer is Claude, review with Codex:
  `codex-yolo -m gpt-5.5`

If the yolo commands are shell functions and are not visible from the current
shell, invoke them through fish:

```bash
fish -lc 'claude-yolo -p --model opus'
fish -lc 'codex-yolo -m gpt-5.5'
```

Do not silently substitute a same-family reviewer. If the requested reviewer
command or model is unavailable, report the blocker.

Do not add `--max-budget-usd`, `--permission-mode`, or equivalent ad hoc
permission/budget flags to Claude review commands. The `claude-yolo` alias owns
permissions, and subscription usage should not be represented as a per-run budget
cap.

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

3. For a Codex implementer, run Claude as a one-shot noninteractive review
   inside tmux. Use a tiny fish wrapper so shell aliases/functions are available
   and the log is tee'd for inspection:

   ```bash
   runner_file="$(mktemp -t review-run.XXXXXX.fish)"
   cat > "$runner_file" <<'FISH'
   set prompt_file $argv[1]
   set log_file $argv[2]
   cat "$prompt_file" | claude-yolo -p --model opus 2>&1 | tee "$log_file"
   set statuses $pipestatus
   printf "\n[claude-yolo pipeline statuses: %s]\n" "$statuses" | tee -a "$log_file"
   read -P "review finished; press Enter to close tmux pane"
   FISH
   tmux new-session -d -s "$session" -c "$PWD" \
     "fish \"$runner_file\" \"$prompt_file\" \"$log_file\""
   ```

   For a Claude implementer using Codex as reviewer, use the same tmux/log
   pattern with the appropriate noninteractive Codex command. If no stable
   noninteractive Codex command is available, fall back to an interactive tmux
   session only after telling the user.

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
   `claude-yolo` / `claude --model opus` child remains. Kill the review process
   group before starting another review; tmux can exit while the Claude child
   continues running.

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
