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

## 2026-06-26 - Tool-disabled Claude Review Failed Again For SRT Transcript Slice

- Repo: podcast.
- Goal or slice: SRT transcript provider implementation.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus.
- Expected: a tool-disabled `claude -p --model opus --no-session-persistence
  --tools ""` review would use the embedded/contextual diff and emit the review
  completion sentinel.
- Actual: one attempt timed out or exited without substantive output, and another
  attempted to inspect files despite disabled tools before exiting without the
  sentinel.
- Impact: two unusable tmux review attempts had to be killed before the actual
  review cycle could start.
- Fix or follow-up: for podcast review cycles, use Claude Code `--permission-mode
  plan` with an explicit read-only tool allowlist (`Read`, `Grep`, `Glob`, and
  limited `Bash(git diff/status/rg/grep/ls)`) instead of `--tools ""` when the
  reviewer needs to inspect the worktree.
- Status: recurrence; workaround successful and re-review closed clean.

## 2026-06-26 - Tool-disabled Claude Review Returned No Sentinel For Download Badge Slice

- Repo: podcast.
- Goal or slice: downloaded episode-row artwork badge implementation.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus.
- Expected: `claude -p --model opus --no-session-persistence --tools ""` would
  perform a read-only review from the self-contained prompt and emit the required
  sentinel.
- Actual: Claude attempted a disabled workflow/tool command, exited with pipeline
  status zero, and did not emit the sentinel.
- Impact: the first tmux review attempt had to be killed and rerun; the review
  completed cleanly after allowing read-only `Read`/`Bash(git diff/status/rg)`
  tools and explicitly disallowing edit/write tools.
- Fix or follow-up: keep sentinel polling mandatory; for this project, prefer
  read-only tool allowlists over fully tool-disabled Claude reviews when direct
  worktree verification is needed.
- Status: recurrence; workaround successful.

## 2026-06-26 - Tool-disabled Claude Review Returned No Sentinel

- Repo: podcast.
- Goal or slice: Episode Detail long-notes bottom-clearance fix.
- Implementer: Codex-family.
- Reviewer: Claude Code / Opus.
- Expected: `claude -p --model opus --no-session-persistence --tools ""` with a
  self-contained diff prompt would produce a read-only review and the required
  completion sentinel.
- Actual: the run exited with no substantive review, logged a tool-use error /
  interrupted request shape, and did not emit the sentinel even though the
  pipeline status was zero.
- Impact: the first tmux review attempt had to be killed and rerun; the usable
  review cycle completed after switching to `--permission-mode plan` with direct
  read-only worktree access.
- Fix or follow-up: do not rely on zero pipeline status as review completion;
  keep sentinel polling mandatory. Prefer plan-mode read-only Claude reviews for
  this project when tool-disabled mode returns empty/tool-error output, and keep
  prompts explicit about no mutation.
- Status: identified.

## 2026-06-25 - Tool-disabled Claude Reviews Need Explicit Limitation Handling

- Repo: podcast.
- Goal or slice: episode-list blank-tail fix.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus via `claude -p --model opus --tools ""`.
- Expected: because the prompt embedded the full diff, the reviewer would complete
  a diff-based review without tool access and clearly state any limitations.
- Actual: the review completed, but reported degraded/empty file-read tooling and
  based findings on the embedded diff only.
- Impact: the cycle was still usable because the prompt was self-contained, but
  warnings needed careful triage and a second review to confirm fixes.
- Fix or follow-up: keep embedding full diffs for tool-disabled reviewers and ask
  them to separate diff-based conclusions from worktree-verified conclusions.
- Status: reinforced.

## 2026-06-25 - Tool-disabled Claude Reviews Can Hallucinate Verification

- Repo: podcast.
- Goal or slice: Episode Detail chapter folding implementation.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus.
- Expected: a read-only `claude -p --tools ""` review would either review the
  supplied context or state that direct verification was unavailable.
- Actual: the first review emitted apparent tool-use/output and reported warnings
  against stale or nonexistent code/docs. A second review with `claude-yolo`,
  explicit read-only instructions, and direct worktree access re-verified the
  findings as invalid and closed clean after a final docs-trace-only re-review.
- Impact: one extra review cycle was consumed and false warnings had to be
  triaged carefully instead of implemented.
- Fix or follow-up: for code-review cycles that require direct verification, do
  not disable tools unless the prompt embeds the exact diff and explicitly asks
  the reviewer to state limitations rather than invent file reads. If a review
  report cites symbols/files that do not exist, verify before changing code and
  use the next cycle to document accepted/rejected findings.
- Status: identified.

## 2026-06-25 - Read-only Claude Reviews Need Self-contained Diffs

- Repo: podcast.
- Goal or slice: episode artwork show-navigation implementation.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus via `claude -p --model opus --tools ""`.
- Expected: the read-only tmux review prompt would let Claude review without tools.
- Actual: the first prompt listed touched files but did not embed the diff, so Claude attempted an unavailable Read tool and ended without the required sentinel.
- Impact: the first review attempt had to be killed and rerun with a self-contained diff prompt.
- Fix or follow-up: when tools are disabled for a reviewer, include the relevant diff/context inline rather than only file paths.
- Status: identified. Recurrence on 2026-06-25 during the transcript-reader
  stabilization review: an initial no-diff prompt again produced no usable
  sentinel, and rerunning with the scoped diff embedded completed normally.
  Recurrence on 2026-06-25 during an Episode Detail chapter-disclosure docs
  review: even with an embedded diff, Claude attempted disabled file reads when
  asked for line references; rerunning with explicit "review only the diff in
  this prompt; do not try tools" completed normally. Recurrence later the same
  day during the download-progress/device-workflow review: Claude emitted a
  disabled Read tool call despite an embedded diff; rerunning with a stronger
  "do not output tool_use JSON; state limitations instead" instruction completed.

## 2026-06-24 - Claude tmux Review Needs Interactive Shell Dispatch

- Repo: podcast.
- Goal or slice: Persistence & Responsiveness Refactor Phase 0 measurement.
- Implementer: Codex / GPT-family.
- Reviewer: Claude Code / Opus via `claude-yolo --model opus`.
- Expected: a detached one-shot tmux command would run `claude-yolo --model opus
  -p` with redirected prompt and log files and leave review output in the log.
- Actual: the detached wrapper exited without durable output; launching a fresh
  tmux shell and sending the fish command into the pane produced normal Claude
  review output.
- Impact: the first review handoff attempts were wasted and had to be rerun, but
  the required review loop completed before commit.
- Fix or follow-up: for Claude yolo review cycles, prefer `tmux new-session`
  followed by `tmux send-keys` into an interactive shell, or use a checked script
  file, instead of deeply nested detached shell/fish/redirection strings.
- Status: identified.

## 2026-06-22 - Pi Review Slot Pool And Empty-Bundle Guard

- Repo: agent-stuff.
- Goal or slice: reduce cross-repo Pi review bottlenecks and prevent false clean
  verdicts after committing.
- Implementer: Pi / GPT-family.
- Reviewer: pending.
- Expected: parallel agents should be bounded by provider capacity, not a single
  global mutex; a review with no git changes should not count as CLEAN.
- Actual: the Pi review harness used one global per-user lock, so unrelated repos
  queued behind each other; after a commit, an empty diff bundle could still be
  handed to Pi and reported as CLEAN.
- Impact: review throughput suffered and agents could report misleading
  post-commit clean reviews.
- Fix or follow-up: changed the Pi harness to use a bounded per-user slot pool
  (default 3, tunable via `--max-concurrent` / `PI_REVIEW_MAX_CONCURRENT`) and to
  fail closed with INVALID when the worktree has no staged, unstaged, or
  untracked changes.
- Status: implemented.

## 2026-06-19 - Run Required Review Before Declaring Slice Complete

- Repo: podcast.
- Goal or slice: refresh-warning suppression for known feed failures.
- Implementer: Pi / GPT-family.
- Reviewer: Claude Code / Opus via `claude-yolo --model opus`.
- Expected: project-required external review cycle would run before reporting the
  implementation as complete or commit-ready.
- Actual: implementation, tests, and docs were completed first, then the user had
  to explicitly ask whether the review cycle had happened.
- Impact: no commit occurred, but the closeout was premature and omitted a
  required quality gate.
- Fix or follow-up: before final implementation summaries in repositories with a
  review-cycle rule, check whether the external review has been run; if not,
  state that plainly and run it before calling the slice complete.
- Status: identified.

## 2026-06-19 - Quote Prompts Through Files For tmux Reviewer Runs

- Repo: podcast.
- Goal or slice: active Queue-row Play idempotence fix.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus via `claude-yolo --model opus`; Pi reviewer via `pi -p`.
- Expected: tmux reviewer commands would pass the generated review prompt to
  non-interactive reviewer CLIs.
- Actual: the first Claude command embedded a fish `$prompt` variable inside a
  double-quoted outer shell command, so the outer shell expanded it to empty and
  Claude exited with "Input must be provided".
- Impact: the first Claude review attempt produced no review and had to be
  relaunched.
- Fix or follow-up: for tmux reviewer runs, write a small script that reads the
  prompt file and invokes the reviewer, then run that script from tmux instead
  of nesting shell/fish variable expansion in one command string.
- Status: identified.

## 2026-06-19 - Root-Analysis Reviews Need Process And Worktree Isolation

- Repo: podcast.
- Goal or slice: Queue row Play root-cause analysis and backlog triage.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus 4.8 via `claude-yolo --model opus`.
- Expected: a read-only root-analysis review plus one backlog edit would leave
  the main worktree otherwise unchanged.
- Actual: after the review, unrelated player-code edits appeared; continued
  polling showed a lingering Claude Code process with cwd in the podcast repo
  still mutating files. The process was killed and all unauthorized code edits
  were reverted before closeout.
- Impact: the review findings were usable, but the main worktree was briefly
  polluted by an external agent process.
- Fix or follow-up: before yolo reviews, check for existing agent processes in
  the target repo; run reviews from isolated/disposable worktrees even for
  analysis-only work; continue auditing and reverting any unauthorized mutations
  before reporting.
- Status: identified.

## 2026-06-18 - Use Isolated Review Worktrees For Yolo Reviewers

- Repo: podcast.
- Goal or slice: iOS player Add-to-Top queue-anchor fix.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus 4.8 via `claude-yolo --model opus`.
- Expected: the reviewer would inspect uncommitted changes read-only in the main
  worktree and report findings without changing files.
- Actual: after the first review cycle, the Swift/test changes were no longer in
  the main worktree, leaving only docs. The cycle correctly caught the missing
  implementation, but the review environment was no longer trustworthy for the
  live worktree.
- Impact: the implementation had to be re-applied before continuing. Later
  cycles were run from isolated temporary review worktrees populated from a
  patch, protecting the main worktree while still giving the reviewer a real
  `git diff` to inspect.
- Fix or follow-up: for yolo reviewer sessions, prefer an isolated review
  worktree or disposable copy with the current patch applied. Always audit the
  main worktree after each review cycle and before final reporting.
- Status: identified.

## 2026-06-18 - Verify Reviewer Read-Only Compliance Before Closeout

- Repo: podcast.
- Goal or slice: backlog-only refresh-warning triage item review.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus 4.8 via `claude-yolo --model opus`.
- Expected: the reviewer would perform read-only inspection in tmux and leave
  only the implementer's backlog change in the worktree.
- Actual: after the final review cycle, unrelated player code/test/backlog edits
  appeared despite read-only instructions. They were detected by `git status`
  and reverted before closeout, preserving only the intended backlog item.
- Impact: the review transcript still produced usable severity findings, but the
  workflow required an explicit post-review worktree audit to avoid committing
  unauthorized reviewer mutations.
- Fix or follow-up: always run `git status`/targeted diff after external review
  cycles before reporting clean; keep reviewer sessions read-only in the prompt,
  but do not trust the prompt alone as a guard.
- Status: identified.

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

## 2026-05-31 - Launch Yolo Review Aliases Through Fish

- Repo: podcast.
- Goal or slice: P1 physical Now Playing surface proof blocker closeout.
- Implementer: Codex / GPT-5.
- Expected: the Codex implementer would run the required Claude review with
  `claude-yolo --model opus`.
- Actual: checking only the default shell PATH made `claude-yolo` look missing,
  because it is a fish function rather than an executable. The review fell back
  to raw `claude --model opus -p`, and a first tmux heredoc attempt also got
  stuck before the reviewer launched.
- Impact: the review still completed with Claude Opus, but it did not use the
  intended project wrapper and wasted closeout time.
- Fix or follow-up: run yolo reviewer aliases through fish in tmux and
  automation: `fish -lc 'claude-yolo --model opus'` or
  `fish -lc 'codex-yolo -m gpt-5.5'`. If `command -v` cannot find an alias,
  verify it with `fish -lc 'type claude-yolo'` / `fish -lc 'type codex-yolo'`
  before falling back to raw CLIs.
- Status: documented in podcast `AGENTS.md`.

## 2026-06-03 - Pi Review Loop Skill Built And Live-Verified

- Repo: agent-stuff (new skill `claude/skills/pi-review-loop/`).
- Goal or slice: a Claude-driven, observable Pi review loop replacing ad-hoc and
  tmux reviewer invocation; built subagent-driven from a reviewed spec + plan.
- Implementer: Claude / Opus 4.8 controller + Sonnet implementer subagents.
- Reviewer: two-stage spec-compliance + code-quality review subagents per task.
- Expected: a pure-stdlib foreground harness that drives Pi as a reviewer over its
  `--mode json` event stream and can never hang invisibly.
- Actual (live smoke against real `pi` / gpt-5.5):
  - Happy path works end to end: model resolved from the real `pi --list-models`,
    bundle built, Pi spawned in its own process group, `agent_end` detected,
    verdict extracted from the final assistant message (`REVIEW: CLEAN`), clean
    teardown, exit 0 in ~5s. The 221 `thinking` blocks were correctly skipped.
  - M2 (provider block) reproduced in the wild after ~10 rapid `pi` calls: Pi
    produced zero output on both streams; the harness correctly STALLED at the
    timeout, killed the process group, left no orphan, wrote `result.json`, exit 2.
- Impact: validated for both the success and the M2-stall paths on the real
  provider, not just against the fake.
- Fix or follow-up: two bugs unit tests could not catch were found and fixed during
  the smoke — (1) `pi --list-models` prints a whitespace TABLE (separate
  provider/model columns) to STDERR, not `provider/model` tokens to stdout, so the
  resolver was silently returning the fallback; (2) the bundle carried only the diff
  with no reviewer instruction, so Pi was never told to emit the `REVIEW:` verdict —
  now supplied via `--append-system-prompt`. The lock keys on the harness PID rather
  than the Pi PGID (documented deviation). The ISSUES verdict path is exercised by
  `fake_pi` unit tests; the trivial real sample returned CLEAN.
- Status: built, reviewed, live-verified, installed via chezmoi; external review round addressed.
- Safety: summary-safe metrics only; no prompts, transcript bodies, tool output,
  secrets, or sensitive personal data.

## 2026-06-15 - Read-Only Claude Review Needed A Tight Verdict Prompt

- Repo: podcast.
- Goal or slice: Show Detail refresh in-progress feedback.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8.
- Expected: the reviewer would inspect the small scoped diff and return Critical,
  Warning, Suggestion findings plus an explicit goal-reached verdict.
- Actual: the first review request remained in source-gathering mode long enough
  to stall the closeout. Interrupting it and sending a tighter no-more-tools
  instruction produced the required report immediately.
- Impact: the review completed with no Critical or Warning findings and an
  explicit "goal reached: yes" verdict, but the loop took longer than necessary.
- Fix or follow-up: for small read-only closeout reviews, include a hard
  instruction to stop after the scoped diff/source pass and emit the verdict. If
  the reviewer keeps expanding context without findings, interrupt and request a
  bounded final report instead of waiting indefinitely.
- Status: identified.

## 2026-06-17 - Claude Review Completed But Missed Sentinel

- Repo: emerge.
- Goal or slice: UMF-114 Slice 3 final follow-up review before commit.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus 4.8 via `claude-yolo --model opus`.
- Expected: the reviewer would emit the required final sentinel after the report
  so the tmux polling wrapper could complete automatically.
- Actual: Claude produced a clean, bounded review report at the input prompt but
  omitted the sentinel line, leaving the polling wrapper waiting.
- Impact: the review result was still usable after direct pane capture, but the
  automation needed manual interruption.
- Fix or follow-up: make sentinel instructions more prominent for Claude review
  prompts, or allow the wrapper to detect the input prompt returning after a
  complete report with findings/no-findings sections.
- Status: identified.

## 2026-06-18 - Claude Print Review Stalled In Tmux With Prompt File

- Repo: podcast.
- Goal or slice: Smart Inbox Ranking first production slice.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus via Claude Code CLI.
- Expected: `claude-yolo --model opus --print < prompt` in a separate tmux
  session would complete the external review and write output to a file.
- Actual: multiple tmux launches stayed alive with zero-byte output, including
  stdin redirection and argument-based prompt variants. The same prompt completed
  through a direct foreground Claude Code Opus invocation.
- Impact: the review cycle completed with no unresolved Critical or Warning
  findings, but the required tmux wrapper path wasted closeout time and needed
  manual cleanup of stuck processes.
- Fix or follow-up: for Claude Code review automation, smoke-test the exact
  prompt transport before waiting on a long run. If tmux output remains zero
  while a direct `claude --print` smoke test succeeds, switch to the known-good
  direct invocation and record the deviation.
- Status: identified.

## 2026-06-18 - Claude Re-Review Failed After Clean First Review

- Repo: django-cast.
- Goal or slice: Podcast publishing metadata first implementation slice.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus via `claude-yolo -p --model opus`.
- Expected: the second Claude review round would run inside tmux with a prompt
  file, emit the required sentinel, and verify fixes from round 1.
- Actual: the first tmux re-review attempt exited with a zero-byte log. A second
  tmux attempt logged runner start and prompt size, then exited before Claude
  output or pipeline status. A foreground `claude-yolo -p --model opus` run with
  the same prompt stayed silent for multiple minutes and was interrupted.
- Impact: implementation checks passed, and Claude round 1 had no Critical or
  Warning findings, but the required clean Claude re-review and final Pi review
  could not be completed in this closeout.
- Fix or follow-up: make the tmux wrapper surface child-process exit details even
  when `claude-yolo` exits before fish pipeline status logging, and provide a
  documented fallback policy for re-review attempts after a clean first review.
- Status: blocked on review tooling.

## 2026-06-22 - Docs-First Review Needs Current-Vs-Target Sweep

- Repo: podcast.
- Goal or slice: docs-first episode lifecycle state model and backlog cleanup task.
- Implementer: Pi / Codex-family.
- Reviewer: Claude Code / Opus via `claude-yolo --model opus`.
- Expected: a three-cycle review loop would reach a clean external review before
  manual handoff.
- Actual: cycle 3 found one remaining current-vs-target wording mismatch in the
  product doc after the reference docs had been qualified; the mismatch was fixed
  after the final allowed cycle, so no fourth clean re-review was run.
- Impact: the slice can be manually reviewed with checks passing, but the review
  loop did not produce a final clean external verdict.
- Fix or follow-up: for docs-first slices that intentionally document desired
  behavior before implementation, include an explicit current-vs-target sweep in
  the first review prompt and grep both reference/current docs and product docs
  for unqualified target claims before re-review.
- Status: identified.

## 2026-06-23 - Claude Review Hit Temporary API Overload

- Repo: emerge.
- Goal or slice: UMF-1339 specs-first persisted Time Domain edit planning.
- Implementer: Codex / GPT-5.
- Reviewer: Claude / Opus via `claude-yolo -p --model opus`.
- Expected: the tmux review wrapper would run a read-only docs/spec review and
  emit the required sentinel.
- Actual: Claude returned API Error 529 Overloaded before producing a review
  report or sentinel.
- Impact: no review findings were available; the attempt did not count as a
  completed review cycle and had to be retried after cleaning up the tmux
  session.
- Fix or follow-up: treat 529 as a transient external failure, kill stale tmux
  sessions, and verify no child Claude process remains before retrying.
  Multiple re-review retries after the initial completed review hit the same
  529 overload. A later user-requested retry completed successfully and closed
  the review with 0 Critical / 0 Warning findings.
- Status: resolved after retry.

- 2026-06-24: Claude no-tools analysis review exited without the required sentinel after asking to read files. Treat this as a prompt/context failure, not a review finding: kill the waiting tmux pane, restart the same round with the relevant file snippets embedded directly, and explicitly instruct Claude to report insufficient context as a finding instead of requesting tools. Status: applied.

- 2026-06-24: Claude Code `-p` review invocations for podcast P2 hung with
  zero-byte logs in tmux and in foreground when using the default text output
  path. A foreground smoke test with `--no-session-persistence --output-format
  json` completed, and the follow-up review completed with that exact mode
  outside tmux. For Claude Code review automation, try JSON print mode before
  spending multiple polling intervals on silent text-mode runs; record any tmux
  deviation separately from the review verdict. Status: identified.

- 2026-06-24: Claude Opus no-tools review for emerge slice 5 first returned
  partial prose and no sentinel after saying it needed to read files. The retry
  succeeded when the prompt explicitly said the reviewer had no tools, must not
  inspect files, and must review only the supplied diff. For no-tools review
  prompts, state the available evidence boundary before the scope and require
  insufficient context to be reported as a finding instead of tool-seeking prose.
  Status: applied.

- 2026-06-24: Claude Opus final-goal review for emerge MI management repeated
  the no-tools failure mode: the first prompt described repo paths and asked for
  inspection, so Claude emitted a tool call and exited without the required
  sentinel. Kill the waiting tmux pane and rerun the same round with the
  evidence boundary first, explicitly saying no repository reads are available
  and insufficient context must be reported as a finding. Status: applied.

- 2026-06-24: Claude Opus review for podcast responsiveness stress proof hung
  for multiple minutes with zero output when given embedded 30KB, 24KB, 14KB,
  and 4KB diff prompts through both tmux and foreground `-p` modes. A tiny smoke
  prompt returned immediately, and a concise risk-summary review prompt returned
  `CLEAN` in tmux. For closeout reviews under this failure mode, first verify
  the CLI with a tiny smoke prompt, then prefer a short evidence summary focused
  on Critical/Warning risks over progressively smaller raw diffs. Status:
  identified.

- 2026-06-25: A Claude no-tools re-review prompt for a docs-only backlog change
  still emitted repeated tool-seeking prose and no sentinel, despite embedding
  the full changed block. The retry succeeded in tmux with `claude-yolo -p` and
  read-only tools (`--allowedTools Read,Grep,Glob`). For re-reviews that ask
  Claude to verify the live file matches a supplied docs excerpt, prefer a
  read-only-tool Claude Code invocation over no-tools analysis, or explicitly
  remove all language about reading/verifying live files. Status: applied.

- 2026-06-25: Claude Opus no-tools round-2 re-review for an emerge frontend
  geometry fix exited without the required sentinel after saying it needed to
  inspect files, even though the diff was embedded. The retry succeeded when the
  prompt opened with an explicit no-tools evidence boundary, supplied the needed
  surrounding code facts, and asked Claude to review only the supplied diff. For
  no-tools re-reviews, put the evidence boundary before any repo/file language
  and include key surrounding facts that would otherwise trigger tool-seeking.
  Status: applied.

- 2026-06-25: Claude Opus no-tools round-2 re-review for emerge MI process
  selection emitted tool-seeking prose and exited without the required sentinel
  even though the full diff was embedded. The retry succeeded when the prompt
  opened with "review from supplied prompt contents only", explicitly said "do
  not use tools", and framed the previous no-sentinel run as invalid. For
  no-tools re-reviews, put the evidence boundary and no-tools instruction in the
  first paragraph and avoid asking Claude to independently verify live files.
  Status: applied.

- 2026-06-25: Claude Opus no-tools review for an emerge table-splitter reset
  fix exited successfully without the required sentinel after emitting attempted
  tool-call markup. The retry succeeded when the prompt explicitly said this
  replaced an invalid no-sentinel attempt and that all code needed for review
  was included in the prompt. For no-tools first-review prompts, put the
  self-contained evidence boundary before the implementation scope and ban tool
  calls/slash commands explicitly. Status: applied.

- 2026-06-25: Claude Opus no-tools round-2 re-review for emerge MI local
  filtering exited with pipeline status 143 and no review text when given a
  full-diff prompt. The retry succeeded with a shorter prompt containing the
  prior findings, verification results, and line-numbered changed snippets. For
  no-tools re-reviews, prefer focused snippets over full raw diffs when the
  changed files are large, and detect pipeline status without sentinel before
  waiting on a runner prompt. Status: applied.

- 2026-06-25: Claude Opus no-tools final re-review for emerge MI validity
  picker exited successfully without the required sentinel after emitting
  attempted tool-call markup. The retry succeeded when the first paragraph
  explicitly said to review only the supplied prompt text, banned tool XML, and
  embedded the exact validation and add-row snippets needed to close the prior
  warning. For no-tools re-reviews, include the decisive source excerpts in the
  prompt and avoid asking Claude to verify live files. Status: applied.

- 2026-06-25: Podcast transcript/metadata fix was validated and device-installed
  before the mandatory cross-agent review loop ran; the user caught the missing
  review step. For projects with AGENTS.md review-cycle requirements, treat
  external review as part of implementation completion, not only commit prep, and
  run it before reporting a slice as fixed/deployed. Status: applied.

- 2026-06-25: Claude Opus no-tools round-2 re-review for emerge MI edit-table
  layout exited without the required sentinel after trying to invoke a skill,
  despite tools being disabled. The retry succeeded when the first paragraph
  explicitly said "Do not use skills" in addition to banning tools and framed
  the prior attempt as invalid. For no-tools Claude reviews, ban both tools and
  skills when the prompt asks for a code review. Status: applied.

- 2026-06-25: Claude Opus no-tools review for emerge CGMES/UCTE selection
  behavior again exited before the sentinel after trying to invoke its own
  review skill. The retry succeeded with a self-contained evidence prompt and
  no tool access; later cycles completed normally. For no-tools Claude review
  loops, keep banning skills alongside tools and treat any pre-sentinel skill
  invocation as an invalid review that needs a focused retry. Status: applied.

- 2026-06-25: Claude Opus no-tools review for emerge MI IGM/CGM edit-table
  header chrome exited without the required sentinel after trying to inspect a
  file through disabled tooling. The retry succeeded when the prompt explicitly
  required review from embedded evidence only, banned tool invocations in the
  first paragraph, and included the surrounding facts needed to evaluate the
  small diff. For no-tools Claude reviews, keep the evidence boundary first and
  include decisive context rather than asking the reviewer to inspect files.
  Status: applied.

- 2026-06-25: Claude Opus no-tools docs review for django-resume first hung
  silently when the prompt was fed on stdin, then exited without the required
  sentinel after emitting attempted terminal-tool markup. The retry succeeded
  after embedding the full diff and line-numbered docs and opening with an
  explicit no-tools evidence boundary. For docs-only no-tools reviews, avoid
  asking Claude to inspect the worktree and provide the exact review evidence
  in the prompt. Status: applied.

- 2026-06-26: Claude Opus no-tools review for emerge UMF-1348 emitted
  fabricated test execution claims and false missing-code findings when the
  prompt asked it to review a diff but also framed verification as something it
  could independently confirm. The re-review succeeded after supplying exact
  local outputs, line-numbered decisive snippets, and the `SL` area-code to
  `SI` dashboard-code alias context. For no-tools reviews, make the embedded
  evidence boundary explicit and include alias/domain facts that are needed to
  judge tests without live command execution. Status: applied.

- 2026-06-26: Claude Opus no-tools review for emerge MI voltage parameter
  typing exited with status 143 and no sentinel because the fish runner picked
  up a timeout-wrapped `claude`, leaving a `claude --model opus` child after
  tmux was closed. The review succeeded after killing the orphaned process
  group and invoking `/opt/homebrew/bin/claude` explicitly from the fish runner.
  For no-tools Claude reviews, check for orphaned Claude children after any
  pre-sentinel tmux failure and bypass shell wrappers with the absolute Claude
  binary when needed. Status: applied.

- 2026-06-26: Claude Opus no-tools review for an emerge Time Domain Qt
  crash fix first exited without the required sentinel after trying to inspect
  files, then exited with status 143 on fuller self-contained prompts. The
  review succeeded only after shrinking the prompt to decisive evidence and a
  summarized code change. For no-tools Claude reviews, use concise decisive
  snippets for small lifecycle fixes and fall back from raw diffs when Opus
  repeatedly exits 143. Status: applied.

- 2026-06-26: Claude Opus no-tools re-review for emerge UMF-1303 readability
  exited with pipeline status 143 and no review text, leaving only the fish
  runner prompt alive in tmux. Killing the stale session and rerunning the same
  focused re-review succeeded, and the final cycle was clean. After pre-sentinel
  status-143 exits, inspect the log before waiting out the full poll loop, kill
  any orphaned Claude child, then retry with the focused prior-findings prompt.
  Status: applied.

- 2026-06-26: Claude Opus no-tools re-review for emerge Model Improvement
  deletion UX exited with pipeline status 143 and no review text, leaving only
  the fish runner prompt in tmux. The active implementation had changed after a
  user-reported false-dirty issue, so the review loop needed a clean retry with
  a shorter focused prompt covering prior findings and the updated diff. For
  small PySide follow-up reviews, prefer concise re-review prompts after fixing
  prior findings instead of repeating all narrative context. Status: applied.

- 2026-06-26: pi noninteractive review for emerge UMF-1286 hung silently when
  run through the tmux/tee wrapper: the pane stayed blank and only the runner
  plus `tee` remained visible, while the same prompt shape worked when `pi -p`
  was run directly with `--no-context-files --approve`. For pi review loops,
  smoke-test direct noninteractive mode first and fall back to direct foreground
  execution if the tmux wrapper has no output and no visible pi child process.
  Status: applied.

## 2026-06-26 - Pi review prompt argument splitting
- Expected: Pi review runner passes the complete prompt as one noninteractive read-only review request.
- Actual: fish command substitution split prompt lines into separate CLI arguments, so bullet lines beginning with `-` were parsed as unknown options.
- Impact: first review attempt did not run and emitted no review sentinel.
- Fix/follow-up: pass prompt after `--` as one quoted argument or use a stdin-safe invocation verified for `pi -p` before starting tmux.
- Status: fixed for rerun.

## 2026-06-26 - Pi review option separator
- Expected: Pi accepts the conventional `--` end-of-options separator before a quoted prompt in noninteractive mode.
- Actual: Pi rejected `--` as an unknown option, exited immediately, and left only the tmux runner waiting at its close prompt.
- Impact: first review attempt did not run and produced no review sentinel.
- Fix/follow-up: invoke `pi -p --no-session --tools read,grep,find,ls "$prompt"` without `--`; inspect short logs before waiting out the full poll window.
- Status: fixed for rerun.

## 2026-06-27 - Pi tmux prompt expansion
- Expected: tmux starts a bash runner that reads the prompt file inside the review pane and passes it to Pi as one `-p` argument.
- Actual: embedding `$(cat "$1")` inside the outer double-quoted `tmux new-session` command expanded before tmux started, so `$1` was empty and the first run printed `cat: "": No such file or directory`.
- Impact: the first review attempt received no prompt and produced no sentinel.
- Fix/follow-up: write a small temporary runner script and pass `prompt_file` / `log_file` as script arguments, so command substitution happens inside the pane with real positional parameters.
- Status: fixed for rerun.

## 2026-07-06 - Pi Tmux Runner Can Stall Before Spawning Pi

- Repo: podcast.
- Goal or slice: Singularity.FM show artwork import.
- Implementer: Codex / GPT-family.
- Reviewer: Pi / openai-codex/gpt-5.5.
- Expected: fish or zsh tmux runners would pass a saved review prompt to
  `pi -p`, stream output through `tee`, and produce the completion sentinel.
- Actual: two tmux attempts stayed blank with a zero-byte log; process checks
  showed only the runner and `tee`, with no visible `pi` child. A tiny direct Pi
  smoke test succeeded, and the direct foreground Pi review completed.
- Impact: the review loop lost time to wrapper startup failures before the real
  review began.
- Fix or follow-up: when a Pi tmux runner has a zero-byte log and no `pi` child
  after a few polls, kill the tmux session, verify no orphaned review process,
  and run the read-only Pi review directly with `--no-session --no-context-files
  --approve` rather than retrying equivalent tmux wrappers.
- Status: applied; cycle 1 produced one Suggestion, cycle 2 was clean.

## 2026-06-27 - Pi Anthropic Review Route Blocked
- Expected: Pi review can use an Anthropic model to keep Codex implementation slices under a different-family reviewer while still satisfying a user request for Pi-run reviews.
- Actual: Pi returned an Anthropic third-party-app extra-usage billing error before review text or the sentinel.
- Impact: the attempted review produced no findings and could not satisfy the different-family review gate.
- Fix/follow-up: when Pi/Anthropic is blocked, either use another available non-GPT Pi model from `pi --list-models` or explicitly record the limitation before retrying with the user-requested Pi/OpenAI model.
- Status: applied for the llm-benchpacks product-offer docs slice.

## 2026-06-28 - Pi tmux wrapper can leave only fish and tee
- Expected: the cross-agent review fish runner would start `pi -p`, stream output
  through `tee`, and emit the required sentinel.
- Actual: the tmux pane and log stayed empty; `ps` showed only the fish wrapper
  and `tee`, with no visible `pi` child, until the session was killed.
- Impact: waiting for the full polling window would not produce a real review
  and would delay the slice.
- Fix/follow-up: when a Pi tmux review has an empty log and no `pi` child after a
  few polls, kill that wrapper, verify no orphaned Pi process remains, and retry
  with the direct foreground `pi -p --no-session --no-context-files --approve
  --model openai-codex/gpt-5.5 --tools read,grep,find,ls "$prompt"` path.
- Status: applied during the podcast retained-catalog download-cleanup slice.

- 2026-06-28: pi read-only review for daybook smoke command repeatedly hung
  silently when the full prompt was fed on stdin through tmux/tee or a direct
  shell pipeline; the wrapper shell remained alive with an empty log and no
  useful reviewer output. A tiny pi prompt worked, and the real review succeeded
  when the prompt was passed as an `@prompt-file` argument with read-only tools.
  For pi review loops, write the prompt to a file and invoke
  `pi -p --no-session --approve --tools read,grep,find,ls @"$prompt_file"`,
  capturing output to a log file. Status: applied.

## 2026-07-01 - Ops-Control Full Test Blocked By Existing Delve Monitoring Metadata

- Repo: ops-control / ops-library.
- Goal or slice: Delve StoreKit backend rollout hardening.
- Implementer: Pi / Codex-family.
- Reviewer: n/a.
- Expected: after installing the local ops-library collection, `just test` in
  ops-control would provide a full green validation gate for the deployment
  config change.
- Actual: playbook syntax, inventory, secrets, and collection installation passed,
  but service metadata validation failed because `delve_monitoring` references a
  missing `delve_monitoring_deploy` role in the installed collection.
- Impact: the slice could still be deployed and smoke-tested, but the broad
  ops-control validation gate is not currently usable as a green commit gate for
  unrelated Delve deployment changes.
- Fix or follow-up: either add the missing monitoring role, change the service
  metadata capability mapping, or document/target a narrower validation gate until
  `delve_monitoring` metadata is fixed.
- Status: open; reported with the StoreKit rollout validation results.

## 2026-07-03 - Pi Review Tmux Environment Not Propagated

- Repo: emerge.
- Goal or slice: Automatic process configuration frontend alignment, Slice 1.
- Implementer: Codex / GPT-family.
- Reviewer: Pi / openai-codex/gpt-5.5.
- Expected: prefixing `REVIEWER_AGENT=pi REVIEWER_MODEL=... tmux new-session`
  would make the fish review runner select Pi inside the tmux pane.
- Actual: the tmux session saw the default reviewer value, selected
  `claude-plan`, and exited before producing the review sentinel.
- Impact: the first review attempt did not run and had to be restarted.
- Fix or follow-up: set the reviewer selection directly inside the runner script
  or pass explicit tmux environment values with a verified method before polling.
- Status: fixed for rerun.

## 2026-07-03 - Pi Review Prompt Handoff Reliability

- Repo: podcast.
- Goal or slice: Startup hydration empty-state guard.
- Implementer: Codex / GPT-family.
- Reviewer: Pi / openai-codex/gpt-5.5.
- Expected: Pi would accept the full review prompt as one positional argument in
  the tmux runner and stream review output.
- Actual: the long positional-prompt runs left the Pi process alive with an
  empty log for several minutes. A tiny Pi probe and a temp-file read probe both
  worked, and the full review completed when the runner passed a short
  instruction telling Pi to read the prompt file.
- Impact: the review loop lost time to two nonproductive attempts before the
  real review started.
- Fix or follow-up: for Pi reviews with substantial prompts, write the prompt to
  a temp file and pass only a short instruction to read that file. Keep a tiny
  direct Pi probe handy to distinguish CLI startup failure from prompt handoff
  trouble.
- Status: applied for rerun and re-review.

## 2026-07-06 - Review Suggestion Missed Test-Only Accessor Use

- Repo: podcast.
- Goal or slice: Periphery dead-code gate restoration.
- Implementer: Codex / GPT-family.
- Reviewer: Claude / Opus.
- Expected: optional cleanup suggestions from re-review would be safe to apply
  when backed by repo-wide reference searches.
- Actual: a re-review suggestion to delete `TranscriptResolutionPlan.candidates`
  missed test-only property reads because the property name matched the enum
  case name; applying it made `just lint-dead` fail during test-target build.
- Impact: the commit loop lost one validation run and required reverting the
  optional cleanup before commit.
- Fix or follow-up: for enum computed properties whose names match cases, verify
  with the compiler/lint gate before accepting static-search-only review
  suggestions; prefer treating such suggestions as deferred unless directly in
  scope.
- Status: applied; the optional deletion was reverted and `just lint-dead`
  passed again.

## 2026-07-08 - Pi Review Blocked By Missing Provider Login

- Repo: emerge.
- Goal or slice: process-configuration `igm_auto_selection` frontend schema
  alignment.
- Implementer: Codex / GPT-family.
- Reviewer: Pi / openai-codex/gpt-5.5.
- Expected: the requested Pi plan review would run before implementation using
  the tmux review-cycle wrapper.
- Actual: Pi exited before review with `No API key found for openai-codex`;
  `pi --list-models` and provider-specific list-model checks reported no
  available models and requested login/API-key setup.
- Impact: the user-requested clean Pi plan-review gate could not run, so
  implementation was not started.
- Fix or follow-up: log Pi into an available provider or export the required
  provider API key before running the review loop; do not silently substitute a
  Codex-family subagent when the user explicitly asks for Pi.
- Status: blocked pending Pi provider configuration.

## 2026-07-08 - Claude Plan-Mode Review Silent Hang

- Repo: podcast.
- Goal or slice: Discovery docs/comment cleanup.
- Implementer: Codex / GPT-family.
- Reviewer: Claude / Opus.
- Expected: a `claude -p --permission-mode plan` read-only tmux review would
  inspect a small three-file diff and emit the completion sentinel.
- Actual: the Claude process stayed alive for several minutes with an empty tmux
  pane and empty log. Retrying with `claude -p --tools ""` and an embedded diff
  completed and emitted the sentinel.
- Impact: the review loop lost several minutes and required terminating the
  silent plan-mode attempt before a substantive review could run.
- Fix or follow-up: for small docs/comment-only diffs, prefer no-tools Claude
  reviews with the exact diff and validation evidence embedded, or fall back to
  that mode after a short empty-log timeout. Kill the silent plan-mode session
  and verify no child Claude process remains before retrying.
- Status: applied for rerun and re-review.
