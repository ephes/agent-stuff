# Review Cycle And Agent Workflow Log

Status: active log

This log captures reusable agent/process lessons from goals, review cycles,
tmux orchestration, skill behavior, validation workflows, and model pairing.
Keep entries summary-safe: record what was expected, what happened instead,
impact, fix or follow-up, and status. Do not include raw prompts, transcripts,
secrets, credentials, or large tool output.

Project-specific execution lessons belong in the project repo, not here.

## Entry Template

```md
## YYYY-MM-DD - Short Title

- Repo:
- Goal or slice:
- Implementer:
- Reviewer:
- Expected:
- Actual:
- Impact:
- Fix or follow-up:
- Status:
```

## 2026-05-29 - Treat No-Report Reviewer Sessions As Invalid

- Repo: podcast / agent-stuff.
- Goal or slice: iOS player refresh-responsiveness follow-up review.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8.
- Expected: a focused Claude Code tmux review would inspect the changed files
  and finish with Critical/Warning/Suggestion counts plus the completion
  sentinel.
- Actual: Claude Code inspected several files, returned to the input prompt,
  and repeated that behavior after a direct request to produce the findings
  report; no usable severity summary was emitted. Follow-up non-interactive
  `--print` attempts with focused prompts also hung without output until
  killed.
- Impact: the attempts could not count as the required external review cycle
  and had to be killed before closeout.
- Fix or follow-up: treat reviewer sessions without an explicit findings
  report as invalid even if prompts contain the sentinel text. Poll for report
  structure near the end of the pane, and restart with a tighter prompt or
  alternate reviewer path instead of accepting echoed prompt text.
- Status: identified.

## 2026-05-28 - Multi-Line Prompts Need Bracketed Paste

- Repo: podcast / agent-stuff.
- Goal or slice: cross-agent review cycle skill.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: a multi-line review prompt could be delivered to a detached
  reviewer TUI with `tmux send-keys -l`.
- Actual: embedded newlines can submit partial prompts, and keys can arrive
  before the reviewer TUI is ready.
- Impact: the reviewer may receive a truncated or empty task, making a review
  cycle appear complete without a meaningful review.
- Fix or follow-up: write the prompt to a temp file, load it into a tmux
  buffer, paste with bracketed paste, and wait for a visible ready state before
  pasting.
- Status: fixed in `cross-agent-review-cycle`.

## 2026-05-28 - Completion Sentinels Must Avoid Prompt Echo

- Repo: podcast / agent-stuff.
- Goal or slice: cross-agent review cycle skill.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: polling for `=== REVIEW COMPLETE ===` would detect when the
  reviewer finished.
- Actual: the prompt itself contained the literal sentinel, so pane capture
  could match the echoed prompt and stop before the reviewer responded.
- Impact: the driver could parse an incomplete pane as a finished review.
- Fix or follow-up: require at least two sentinel matches, fail closed if the
  second match never appears, and avoid printing repeated full captures while
  polling. When quoting prior review reports, strip their trailing sentinel so
  quoted history cannot supply the second match.
- Status: fixed in `cross-agent-review-cycle`.

## 2026-05-28 - Claude Prompt Glyph Needs Readiness Match

- Repo: podcast / agent-stuff.
- Goal or slice: badpod duration review cycle.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: the scripted tmux readiness check would recognize Claude Code's
  input UI before pasting the review prompt.
- Actual: Claude Code showed the `❯` prompt glyph, but the readiness regex did
  not include that glyph and timed out despite the TUI being ready.
- Impact: the review cycle needed manual pane inspection and a second paste
  step before review could start.
- Fix or follow-up: include Claude Code's `❯` prompt glyph in future readiness
  checks, or use a tool-specific ready-state predicate that covers both ASCII
  and Unicode prompt glyphs.
- Status: identified.

## 2026-05-29 - Claude Prompt Glyph Fix Applied To Review Skill

- Repo: podcast / agent-stuff.
- Goal or slice: iOS player action-semantics review cycle.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8.
- Expected: the scripted tmux readiness check would recognize Claude Code's
  input UI before pasting the review prompt.
- Actual: the same `❯` prompt glyph mismatch recurred because the local
  `cross-agent-review-cycle` skill still omitted that glyph.
- Impact: round 1 needed manual pane inspection and a second paste step before
  review could start.
- Fix or follow-up: added `❯` to both Codex and Claude
  `cross-agent-review-cycle` readiness regex examples.
- Status: fixed in the local skill docs.

## 2026-05-28 - Do Not Feed Claude Code Reviews Through Redirected Stdin

- Repo: podcast / agent-stuff.
- Goal or slice: podcast show-description rendering review cycle.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: launching `claude-yolo --model opus < prompt > log` in tmux would
  run a non-interactive review and write the report to a log.
- Actual: Claude Code started as an interactive TUI, stayed blank in the
  redirected log, and did not produce a review report until relaunched with the
  tmux paste procedure.
- Impact: the first review attempt stalled and had to be killed before a valid
  review cycle could begin.
- Fix or follow-up: for Claude Code reviews, launch the fish alias in tmux,
  wait for the visible TUI prompt, paste the temp-file prompt with a tmux
  buffer, and poll pane capture for the completion sentinel.
- Status: reinforced existing `cross-agent-review-cycle` procedure.

## 2026-05-28 - Restart Claude Review After Modified-Thinking API Error

- Repo: podcast.
- Goal or slice: player data-needs docs review.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: a long-running Claude Code review would finish with a severity
  summary after inspecting the staged docs.
- Actual: Claude Code stopped with `API Error: 400 ... thinking or
  redacted_thinking blocks in the latest assistant message cannot be modified`
  before emitting a usable review report.
- Impact: the review attempt had no valid Critical/Warning/Suggestion counts
  and could not be used as the required external review cycle.
- Fix or follow-up: kill the broken tmux session and start a fresh reviewer
  session with a tighter prompt. Treat API-error sessions as invalid review
  cycles unless they already produced a complete findings summary.
- Status: identified.

## 2026-05-28 - Missing Reviewer Wrapper Requires Explicit Fallback

- Repo: podcast / agent-stuff.
- Goal or slice: iOS player backlog grooming review cycle.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.7.
- Expected: `claude-yolo --model opus` would be available, including through
  `fish -lc`, for the required different-family review.
- Actual: the wrapper was not on PATH and was not available through fish. The
  installed Claude CLI was available, but a full-diff non-interactive prompt
  produced no output until killed; a shorter focused prompt with an explicit
  timeout completed successfully in tmux.
- Impact: blindly following the wrapper command would block closeout, and a
  large redirected prompt can waste review-cycle time without producing a
  usable report.
- Fix or follow-up: check both the wrapper and fish alias early. If missing,
  report the exact fallback before using the installed reviewer CLI. Prefer a
  focused prompt for re-reviews and use a timeout so hung reviewer attempts do
  not remain ambiguous.
- Status: identified.

## 2026-05-30 - Kill Wedged Reviewer After Failed Parallel Tool Call

- Repo: podcast.
- Goal or slice: active iOS player bug slice review.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8.
- Expected: Claude Code would inspect the worktree read-only and finish with
  the required review sentinel.
- Actual: the reviewer started a parallel tool sequence, one command failed,
  subsequent tool calls were repeatedly cancelled, and the session never
  emitted a report. It also wrote a temporary `.review_tmp_diff.txt` file into
  the repo despite the read-only review instruction.
- Impact: the attempt produced no valid severity counts and briefly dirtied the
  worktree with reviewer scratch output.
- Fix or follow-up: remove reviewer-created scratch files, kill the wedged
  session, and restart with a tighter prompt that forbids repo-local temp files
  and asks the reviewer to avoid parallel tool calls. Treat wedged attempts
  without a sentinel as invalid review cycles.
- Status: identified.

## 2026-05-30 - Active Player Bug Slice Closeout Review

- Repo: podcast.
- Goal or slice: active iOS player bug slice closeout after queue integrity,
  Inbox-to-Queue feedback, action semantics, large-refresh active intake,
  Add Subscription dismissal, and Queue action-placement fixes.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8.
- Review round: closeout/follow-up after prior 0 Critical / 0 Warning / 3
  Suggestion review.
- Findings this round: 0 Critical, 0 Warning, 1 Suggestion.
- Disposition this round: the single Suggestion was minor dead-code cleanup in
  a history archive accessibility-identifier branch that is not rendered;
  deferred as harmless and not required for closeout.
- Prior round disposition confirmed: 2 Suggestions fixed, 1 naming Suggestion
  intentionally deferred as non-defective.
- Outcome: review cycle can close; another review pass is not warranted.
- Subagents materially affected review: no.
- Safety: summary-safe metrics only; no prompts, transcript bodies, tool
  output, secrets, credentials, or sensitive personal data included.

## 2026-05-30 - Quote Literal Backticks In Shell Search Patterns

- Repo: podcast.
- Goal or slice: active five-bug iOS player batch verification.
- Implementer: Codex / GPT-5.
- Expected: a final `rg` sanity search would scan for stale backlog/code
  phrases without changing the worktree or rerunning build recipes.
- Actual: the search pattern was wrapped in double quotes and contained
  Markdown backticks around `just ios-test` / `just ios-uitest`; the shell
  evaluated those command substitutions and accidentally started the iOS test
  recipes.
- Impact: an in-progress UI result bundle was interrupted and had to be
  replaced with a clean full `just ios-uitest` rerun.
- Fix or follow-up: put literal search patterns containing backticks in single
  quotes, or pass patterns through files/arrays that avoid shell expansion.
- Status: identified.

## 2026-05-30 - Count Review Sentinels After Nudge Prompts

- Repo: podcast.
- Goal or slice: active five-bug iOS player batch external review.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8.
- Expected: the review poll would wait for one echoed sentinel from the prompt
  and one sentinel from the reviewer report.
- Actual: after a nudge prompt also included the sentinel text, the poll's
  two-match condition became insufficient and briefly treated prompt text as a
  completed review.
- Impact: the session needed a corrected poll condition before the real review
  report could be captured safely.
- Fix or follow-up: when nudging a reviewer with sentinel text, increase the
  expected count or check for the output contract around the final sentinel
  instead of using a fixed two-match rule.
- Status: identified.

## 2026-05-30 - Retry Reviewer Overload With Fresh Session

- Repo: podcast.
- Goal or slice: active five-bug iOS player batch physical-evidence closeout
  review.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8.
- Expected: the focused read-only reviewer would inspect the post-review
  device-test and backlog changes and emit the required sentinel.
- Actual: the first reviewer attempt exhausted API retries with a server-side
  529 overload before producing any report or sentinel.
- Impact: the attempt was not a valid review cycle and left a sentinel polling
  command waiting for output that could never arrive.
- Fix or follow-up: kill the failed tmux session and its sentinel poll, then
  retry in a fresh session with a tighter focused prompt. Treat provider
  overload before any report as an infrastructure failure, not a completed
  review round.
- Status: identified.

## 2026-05-30 - Backtick Search Pitfall Recurred During Closeout

- Repo: podcast.
- Goal or slice: active five-bug iOS player batch final sanity checks.
- Implementer: Codex / GPT-5.
- Expected: a final backlog `rg` search would only inspect docs.
- Actual: the search pattern again used double quotes around Markdown backticks,
  causing shell command substitution and accidentally starting `just
  ios-uitest`.
- Impact: the in-progress accidental test run had to be killed, which replaced
  the prior UI result bundle; the full UI suite then had to be rerun to restore
  valid evidence.
- Fix or follow-up: never type final sanity search patterns containing Markdown
  backticks directly in double quotes. Use single quotes by default for `rg`
  patterns copied from docs, especially in closeout checks.
- Status: repeated; needs habit-level correction.
