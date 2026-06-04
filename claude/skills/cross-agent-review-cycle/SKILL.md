---
name: cross-agent-review-cycle
description: Use before committing an implementation slice when the project requires an external tmux review loop, especially when Claude implemented the slice and Codex should review it, or when coordinating up to three fix/re-review cycles with claude-yolo or codex-yolo.
---

# Cross-Agent Review Cycle

## Purpose

Run a bounded independent review loop before committing an implementation
slice. The reviewer must be a different model family from the implementer.

## Reviewer Selection

- If the implementer is Claude, review with Codex:
  `codex-yolo -m gpt-5.5`
- If the implementer is Codex, review with Claude:
  `claude-yolo --model opus`

If the yolo commands are shell functions and are not visible from the current
shell, invoke them through fish:

```bash
fish -lc 'codex-yolo -m gpt-5.5'
fish -lc 'claude-yolo --model opus'
```

Do not silently substitute a same-family reviewer. If the requested reviewer
command or model is unavailable, report the blocker.

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

2. Start the reviewer in the repo root. For a Claude implementer:

   ```bash
   tmux new-session -d -s "$session" -c "$PWD" "fish -lc 'codex-yolo -m gpt-5.5'"
   ```

   For a Codex implementer:

   ```bash
   tmux new-session -d -s "$session" -c "$PWD" "fish -lc 'claude-yolo --model opus'"
   ```

3. Write the self-contained review prompt to a temp file:

   ```bash
   prompt_file="$(mktemp -t review-prompt.XXXXXX)"
   trap 'rm -f "$prompt_file"' EXIT
   printf '%s' "$review_prompt" > "$prompt_file"
   ```

4. Wait until the reviewer TUI appears ready for input before pasting. Do not
   paste while the pane is blank, loading configuration, or showing an error:

   ```bash
   ready=0
   for _ in $(seq 1 30); do
       pane="$(tmux capture-pane -pt "$session" -S -80 2>/dev/null || true)"
       if printf '%s\n' "$pane" | grep -Eiq '(❯|›|>|esc|enter|prompt|message|what can i help|ready)'; then
           printf '%s\n' "$pane" | tail -40
           ready=1
           break
       fi
       sleep 1
   done
   if [ "$ready" -ne 1 ]; then
       echo "Reviewer TUI did not appear ready; attach to inspect before sending the prompt." >&2
       exit 1
   fi
   ```

   If the captured pane does not clearly show the reviewer input UI, stop and
   attach to inspect before sending the prompt.

5. Paste the prompt as a bracketed paste, then submit it once. Do not use
   `send-keys -l` for multi-line prompts because embedded newlines can submit
   partial messages:

   ```bash
   buffer="review-prompt-$session"
   tmux load-buffer -b "$buffer" "$prompt_file"
   tmux paste-buffer -p -b "$buffer" -t "$session"
   tmux send-keys -t "$session" Enter
   ```

6. Poll output until the reviewer prints the required completion sentinel. The
   prompt itself contains the sentinel text, so wait for at least two matches:
   one echoed from the prompt and one emitted by the reviewer.

   ```bash
   completed=0
   for _ in $(seq 1 180); do
       output="$(tmux capture-pane -pt "$session" -S -2000)"
       if [ "$(printf '%s\n' "$output" | grep -Fc '=== REVIEW COMPLETE ===')" -ge 2 ]; then
           printf '%s\n' "$output"
           completed=1
           break
       fi
       sleep 10
   done
   if [ "$completed" -ne 1 ]; then
       echo "Review did not emit completion sentinel; keep the session open and inspect it." >&2
       exit 1
   fi
   ```

7. When the review is complete, keep the session available until the cycle is
   resolved. Kill only when the report has been captured or summarized:

   ```bash
   tmux kill-session -t "$session"
   ```

## Review Prompt Contents

The prompt must say this is a review task, not implementation. Include:

- review round number and whether it is first review, re-review, or final
  allowed review
- implementation intent and scope
- relevant project instructions, specs, docs, or backlog item paths
- touched files and what changed
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
