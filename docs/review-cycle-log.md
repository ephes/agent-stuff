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

## 2026-07-25 - Safety Specs Need Identities And Choreography, Not Adjectives

- Repo: daybook Apple Photos archive/render preparation planning.
- Goal or slice: converge completed discovery documentation and define the
  next non-destructive implementation handoff.
- Implementer: Codex.
- Reviewer: Pi using `openai-codex/gpt-5.6-sol`.
- Expected: explicit selection, plan-by-default operation, verified Fractal
  packages, pinned quality, and no Photos mutation would be enough to make the
  next slice implementation-ready.
- Actual: three reviews found nine, four, and five warnings where words such as
  “mounted,” “pinned,” “idempotent,” and “verified” still hid implementation
  choices: persistent versus transient mount identity, lock/token choreography,
  package/adoption schemas, reproducible and use-time tool identity,
  deterministic metadata/raster mapping, SMB normalization/fsync publication,
  recovery-schema boundaries, partial batches, and privacy/process tests.
- Impact: a fresh implementer would have had to invent safety-critical behavior
  despite the handoff appearing detailed.
- Fix or follow-up: planning for durable filesystem workflows must define
  closed schemas, exact persistent identities, transient run tokens, lock
  lifetimes, commit points, crash/adoption evidence, bounded tools, and
  fail-fast/resume semantics. Treat existing patterns as evidence to inspect,
  not automatically reusable primitives.
- Status: all 18 findings were accepted and the documentation was tightened.
  The bounded three-cycle gate ended with the five final fixes not re-reviewed,
  so the slice is not independently CLEAN. After that limitation and the final
  fixes were reported, the user explicitly directed the synchronized
  documentation to be committed.

## 2026-07-25 - Finish Review-Clean Automation With Its Real GUI Context

- Repo: daybook, ops-library, and ops-control Apple Photos discovery rollout.
- Goal or slice: install and activate the reviewed twice-daily Studio
  LaunchAgent, then prove one scheduled-context run end to end.
- Implementer: Codex.
- Reviewer: Pi using `openai-codex/gpt-5.6-sol` in fresh read-only sessions.
- Expected: local tests, Ansible check mode, disabled-first installation, and
  successful manual runs as the service user would cover the production
  boundary.
- Actual: the real Aqua LaunchAgent reached a one-time macOS sandbox approval
  while opening the Photos library, although the same launcher had succeeded
  through an SSH/manual context. After the user approved it, the waiting
  LaunchAgent completed with exit code 0.
- Impact: stopping after a manual service-user run would have left the schedule
  apparently healthy but unable to complete its first unattended
  reconciliation.
- Fix or follow-up: production verification for macOS GUI-user automation must
  include an exact launchd-context kickstart and observation through completion,
  including privacy prompts, persistent enabled state, aggregate-only logs, and
  unchanged-state idempotency. Keep check mode and manual runs as earlier gates,
  not as substitutes for this final one.
- Status: resolved; the scheduled-context run reconciled all 1,619 entries
  unchanged, preserved the ledger hash, emitted no error output, and the
  twice-daily service remains enabled and idle.

## 2026-07-16 - Pi Implementation Reports Need Sentinel Validation Too

- Repo: podcast.
- Goal or slice: local-search P0 representative-scale and lifecycle closeout.
- Implementer: Pi / Codex-family.
- Reviewer: Pi / Codex-family, fresh read-only sessions required by the task.
- Expected: the one-shot implementation session would finish with its required
  completion sentinel and a compact verification report.
- Actual: the initial implementation output was truncated and omitted the
  sentinel even though useful worktree changes were present and the process
  exited; the primary agent treated the report as invalid, inspected the diff,
  and used a fresh correction session before review.
- Impact: accepting process status or visible edits alone would have skipped an
  explicit handoff/verification boundary and could have advanced an incomplete
  slice into review.
- Fix or follow-up: apply the same fail-closed sentinel rule to delegated
  implementation sessions as to reviews; keep the worktree, independently audit
  it, and use a fresh bounded session for missing closeout work rather than
  inferring completion.
- Status: resolved; the slice subsequently completed three valid review cycles
  and closed CLEAN.

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

## 2026-06-26 - Tool-Disabled Claude Review Tried To Use Tools Before Sentinel

- Repo: django-chat.
- Goal or slice: transcript-storage deletion mitigation.
- Implementer: Codex / GPT-family.
- Reviewer: Claude Code / Opus via `claude -p --model opus --tools ""`.
- Expected: a self-contained diff prompt with disabled tools would produce a
  complete read-only review ending in the required sentinel.
- Actual: Claude emitted apparent tool-use narration and exited without the
  sentinel, though it did surface actionable concerns from the embedded diff.
- Impact: the first review attempt could not count as a completed review cycle,
  but its partial findings were still triaged before rerunning the gate.
- Fix or follow-up: strengthen no-tools prompts to say the reviewer must review
  only the embedded diff and must not output tool-call narration; continue
  treating missing-sentinel reviews as incomplete workflow failures.
- Status: identified. Recurrence in the same django-chat review loop: one
  re-review attempt exited with Claude status 143 and no content beyond pipeline
  status; it was not counted as a completed cycle and was retried with a smaller
  prompt.

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

## 2026-06-27 - Pi Anthropic Review Route Blocked (superseded)
- Expected at the time: Pi review could use an Anthropic model to keep Codex implementation slices under a different-family reviewer while still satisfying a user request for Pi-run reviews.
- Actual: Pi returned an Anthropic third-party-app extra-usage billing error before review text or the sentinel.
- Impact: the attempted review produced no findings and could not satisfy the different-family review gate.
- Fix/follow-up: superseded on 2026-07-12. Mandatory Pi reviews use
  `openai-codex/gpt-5.6-sol` only. Never fall back to Anthropic, another
  non-GPT provider, OpenRouter, or a local model; fail closed instead.
- Status: historical incident retained, unsafe fallback guidance withdrawn.

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

- 2026-06-25: Claude Opus no-tools review for django-cast editor media/detail
  slice repeatedly failed before a usable review: a large stdin prompt hung with
  an empty log, a smaller prompt returned "The model's tool call could not be
  parsed", and a compact direct no-tools prompt hung before ending with
  "Execution error" when interrupted. The smoke test showed
  `--tools=""` works for tiny prompts, so the failure appears prompt/runtime
  specific rather than tmux alone. For future large no-tools reviews, start with
  a minimal evidence-bound prompt that explicitly bans tools and skills in the
  first paragraph, use `--tools=""`, and validate completion on a small
  representative diff before starting the full review loop. Status: observed.

- 2026-06-25: Claude Opus no-tools round-2 re-review for django-cast editor
  media/detail fixes returned a conditional video-timeout warning because the
  prompt included the upload view but not the model method that swallows optional
  poster probe failures. The final re-review closed cleanly after adding the
  decisive `models/video.py` excerpt and a focused poster-timeout regression
  test. For no-tools re-reviews, include the downstream implementation context
  for any behavior asserted by a view, not only the immediate file under review.
  Status: applied.

- 2026-06-26: Claude Opus no-tools re-review for django-cast editor
  media/detail follow-up returned only conditional findings when the prompt
  omitted the code diff, then two larger stdin prompts hung with empty logs even
  after reducing from full diff to focused excerpts. The implementation had
  already passed `just check`, and the remaining conditional warning was covered
  by an added same-type unsupported-placeholder swap regression test. For
  future large no-tools reviews, do not rely on progressively larger stdin
  prompts after the first silent hang; switch to a smaller single-question
  reviewer prompt or use a reviewer configuration that can inspect files
  read-only. Status: observed.

- 2026-06-26: Claude Opus no-tools review for django-cast public transcript
  storage split hung silently for more than ten minutes with an empty log when
  fed a large stdin prompt containing full diffs and planning notes. The process
  stayed alive until manually stopped and left no child after killing the tmux
  session. For this review shape, start with a compact evidence-bound prompt,
  explicitly ban tools and skills in the first paragraph, and include only the
  decisive code/docs excerpts needed for the migration and storage-contract
  review. Status: applied.

- 2026-06-26: Claude Opus no-tools re-review for django-chat django-cast bump
  exited before the required sentinel after emitting attempted read-tool markup,
  even though `--tools ""` was set. The prompt still invited live verification
  of key files. For no-tools re-reviews, open with an explicit evidence-only
  boundary that bans tools and skills, state that attempted tool markup makes
  the review invalid, and include focused excerpts with line numbers instead of
  asking the reviewer to inspect the checkout. Status: applied.

- 2026-06-28: pi read-only review for daybook smoke command repeatedly hung
  silently when the full prompt was fed on stdin through tmux/tee or a direct
  shell pipeline; the wrapper shell remained alive with an empty log and no
  useful reviewer output. A tiny pi prompt worked, and the real review succeeded
  when the prompt was passed as an `@prompt-file` argument with read-only tools.
  For pi review loops, write the prompt to a file and invoke
  `pi -p --no-session --approve --tools read,grep,find,ls @"$prompt_file"`,
  capturing output to a log file. Status: applied.

- 2026-06-29: pi read-only review for the emerge Validation Status From
  MergeManager plan could not start because pi reported no configured models
  and no API key for the configured provider before reading the prompt. Explicit
  provider checks for google and openai-codex also returned "No models
  available". Treat this as an authentication/configuration blocker rather than
  a review finding; do not silently substitute a different reviewer when the
  user explicitly requested pi. Status: blocked.

- 2026-06-29: Claude Opus no-tools re-review for emerge enriched merge slots
  exited cleanly but without the required sentinel after emitting attempted
  tool invocation markup. The prompt said "verify by reading actual files" even
  though it also embedded the diff and disabled tools. For no-tools reviews,
  make the evidence-only boundary the first instruction, explicitly state that
  tool markup invalidates the cycle, and ask the reviewer to use only the
  embedded diff/excerpts. Status: applied.

- 2026-06-29: pi read-only review for emerge enriched merge slots succeeded
  for a tiny smoke prompt, but multiple review prompts using read-only tools
  (`read,grep,find,ls`) stayed alive with empty logs until manually stopped,
  even after reducing scope and disabling context/skills/extensions. A direct
  no-tools evidence-only prompt with focused source diff completed and produced
  actionable findings; the re-review also completed cleanly. For pi reviews
  where tool-backed file reading hangs silently, stop the run and switch to a
  no-tools prompt with only decisive diff excerpts. Status: applied.

- 2026-07-01: Claude Opus no-tools review for django-cast editor API
  rendered-preview endpoints exited without the required sentinel after
  emitting attempted read-tool markup, despite `--tools ""`. The prompt still
  invited the reviewer to examine source files beyond the embedded diff. Treat
  that output as an invalid review, kill the tmux session after confirming no
  Claude child remains, and rerun with an evidence-only prompt that explicitly
  bans tool use and bases findings only on embedded status/diff/check results.
  Status: applied.

- 2026-07-01: Claude Opus no-tools re-review for django-cast podcast
  `itunes:type` support exited without the required sentinel after reporting
  "The model's tool call could not be parsed" even though tools were disabled
  and the full diff was embedded. Treat this as an invalid review rather than a
  finding, kill the tmux session, and rerun with a shorter evidence-only prompt
  that explicitly forbids tool calls/tool markup and focuses on prior findings
  plus changed excerpts. Status: applied.

- 2026-07-01: django-cast transcript sanitizer Pi review exited immediately
  with no log when launched through an inline tmux command containing nested
  prompt/log quoting. Relaunching through a small runner script and passing the
  prompt as `@"$prompt_file"` produced a clean sentinel-bearing review. The
  follow-up Claude Opus no-tools review emitted a complete clean report and
  required sentinel but returned process status 1; treat the sentinel-bearing
  report as review evidence, record the anomalous status, and verify no Claude
  child remains before closing the loop. Status: observed.

- 2026-07-06: django-cast Pi review prompt construction failed before launch
  because a zsh loop used `path` as the iteration variable, which overwrote the
  shell's special `path`/`PATH` array and made later commands such as `sed`
  unavailable. Use neutral names such as `file_path` in zsh review-run scripts,
  especially before invoking commands while building prompt bundles. Status:
  applied.

- 2026-07-06: django-cast strict mypy rollout Pi reviews hung silently when
  launched with read-only tools for some focused prompts; the wrapper process
  remained alive with no reviewer output. Re-running the same evidence-bound
  prompts with `pi -p --no-session --approve --no-tools @"$prompt_file"`
  produced sentinel-bearing reviews. For this repo, prefer compact embedded
  diffs and no-tools Pi prompts when tool-backed Pi review stalls. Also avoid
  parallel DB-heavy targeted pytest runs in this suite; they can surface
  transient SQLite lock failures that disappear when rerun sequentially.
  Status: applied.

- 2026-07-08: daybook Pi review first launched `pi` as a background child
  outside the tmux session while tmux only tailed the log; the process exited
  with an empty log and no sentinel. Relaunching with a small foreground runner
  script inside tmux and passing the prompt as `@"$prompt_file"` produced
  sentinel-bearing reviews. Keep the reviewer process itself as the tmux
  foreground command instead of backgrounding it from the parent shell. Status:
  applied.

- 2026-07-09: django-cast custom editor-block plan review had two process
  pitfalls. Building a prompt with an unquoted heredoc expanded Markdown
  backticks and accidentally started local commands; use quoted heredocs or
  append prebuilt files when prompts contain code fences/backticks. The first
  Pi tmux launch also exited before creating a log because of nested quoting
  around the `@"$prompt_file"` argument; invoking `pi -p --no-session --approve
  ... @"$prompt_file"` directly produced sentinel-bearing reviews. Status:
  applied.

- 2026-07-09: daybook Cheap Oracles Fable review ran successfully in tmux, but
  sandboxed `tmux has-session` checks could not access the host tmux socket and
  returned status 1. Hiding stderr made that look like an exited review. Inspect
  host-launched review sessions with the same escalated tmux context, and do not
  interpret a nonzero status as session exit until `Operation not permitted`
  has been ruled out. Two Fable rounds completed with sentinels; round 2 had no
  Critical or Warning findings. Status: applied.

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

## 2026-07-10 - Consolidated: Fail-Closed Verdict And Lifecycle Contract

- Repo: agent-stuff.
- Scope: supervised Claude review lifecycle, structured output, error mapping,
  interruption, and global serialization.
- Durable lesson: a review gate must distinguish findings from infrastructure
  failure. Schema-invalid or missing verdicts, provider errors, stalls, crashes,
  unexpected exceptions, and user interrupts all produce failed states and exit
  2; only schema-consistent CLEAN can exit 0.
- Implementation: the runner owns a separate reviewer process group, drains and
  records stream evidence, terminates and reaps on deadlines and Ctrl-C, and
  always attempts a structured result. The lock holds an OS advisory guard across
  acquisition, reclaim, ownership, and release; it also uses atomic mkdir,
  unique stale tombstones, metadata owner tokens, and token-checked updates.
- Verification: lifecycle, timeout, malformed-output, provider, SIGINT subprocess,
  process-group escalation, stale-reclaim race, and replacement-owner tests.
- Status: implemented; covered by the 155-test standard suite.

## 2026-07-10 - Consolidated: Isolation Is A Capability And Target Boundary

- Repo: agent-stuff.
- Scope: Claude configuration, filesystem isolation, tool policy, delegation,
  and live inspection targets.
- Durable lesson: allowing a tool name is not enough. Reviewer capabilities must
  be constrained both by OS isolation and by validating each requested target.
- Implementation: safe mode, no setting sources, strict empty MCP, dontAsk,
  read-only inspection tools, no filesystem writes, no raw-repository access,
  and explicit rejection of Bash/edit/delegation/web/MCP tools. Read, Grep, and
  Glob targets are canonicalized against the harness-owned artifact root;
  absolute, tilde, traversal, and out-of-root requests invalidate the review even
  if the sandbox would deny them. Incomplete stream-start inputs are deferred
  until the complete tool call arrives.
- Verification: unit and runner tests cover allowed artifact reads, forbidden
  tools, malformed inputs, /etc/hosts, traversal, tilde, and absolute Glob
  patterns. The installed-Claude canary covers outside-root, raw-repository,
  mixed-case secret paths, denied Grep, and a permitted artifact control.
- Status: implemented; production invocation remains covered by the passing
  six-case installed-Claude Haiku canary.

## 2026-07-10 - Consolidated: Redaction And Git Collection Must Be Byte-Exact

- Repo: agent-stuff.
- Scope: Git invocation, secret detection, private-key state, encodings, control
  characters, and exact model egress.
- Durable lesson: redaction must model Git's actual byte and record structure,
  including removed lines, hunk headings, blank-context configuration, lone CR,
  Unicode line separators, and non-UTF repository data.
- Implementation: Git disables external/textconv drivers, color, mnemonic/no
  prefixes, and suppressed blank markers. Raw stdout bytes are decoded explicitly
  without universal-newline conversion. Secret paths, key blocks, connection
  credentials, token families, JSON/assignment keys, and base64url values are
  redacted. Replacement decoding is recorded and scopes CLEAN; caller context
  remains strict UTF-8. Bundle and prompt writes disable newline translation.
- Verification: focused tests cover secret filenames with spaces, color/ANSI,
  removed key blocks across hunks, function headings, blank key lines, CR/control
  characters, non-UTF Git/untracked data, and exact prompt suffix bytes.
- Status: implemented; redaction metadata remains part of the gate result.

## 2026-07-10 - Consolidated: Review Evidence Must Be Complete, Bounded, And Scoped

- Repo: agent-stuff.
- Scope: staged/unstaged/untracked collection, explicit context, trust boundaries,
  bundle limits, skips, truncations, and audit artifacts.
- Durable lesson: a CLEAN verdict is meaningful only for exact, attributable
  evidence. Caller-authored context must be structurally separated from
  repository-controlled data, and every omission or lossy transformation must be
  visible in authoritative result metadata.
- Implementation: the bundle includes staged, unstaged, and regular untracked
  content; never follows symlinks or opens special files; fails hard for unsafe
  explicit context; preserves mandatory diffstat/context sections; bounds
  per-file and total evidence; and records skipped files, truncations, redactions,
  and affected Git commands. Only context before the repository-evidence boundary
  is trusted. Prompt delivery stays on stdin and artifacts preserve exact input.
- Verification: tests cover forged headings, blocking file types, oversized
  sections, droppable manifests, filenames with spaces/control characters,
  missing/binary/non-UTF context, scoped CLEAN serialization, and exact artifacts.
- Status: implemented; operators must inspect scope metadata before accepting a
  scoped CLEAN.

## 2026-07-10 - Consolidated: One Claude Gate, Reliable Alternate Routing

- Repo: agent-stuff.
- Scope: cross-agent workflow consolidation, Pi/Codex branches, deployment path,
  verification policy, and documentation.
- Durable lesson: keep one authoritative Claude gate and make alternate-agent
  transport match its proven reliability constraints instead of maintaining
  contradictory review paths.
- Implementation: every Claude alias delegates to claude-review-loop; direct
  Claude tmux/plan/Bash-allowlist paths are removed. Codex and Pi remain separate
  tmux branches with resolved reviewer/model arguments passed explicitly. Pi uses
  @prompt-file with direct log redirection, never a large positional prompt or
  tee pipeline. The repository documents the shared review workflow's current
  ~/projects/agent-stuff deployment-path exception.
- Verification: mirrored Codex/Claude skill instructions are kept in sync; skill
  validation, Python compilation, diff checks, 155 standard tests, paid isolation
  canaries when invocation policy changes, and a fresh different-family review
  form the completion gate.
- Status: implemented; packaging remains deferred until the local workflow is
  stable.

## 2026-07-12 - Pi Preflight Rejects Provider-Qualified Model Lookup

- Repo: ws-ops-misc review workflow.
- Expected: Pi preflight accepts the provider-qualified model used by
  `pi --model anthropic/claude-opus-4-8`.
- Actual: the stale tmux server exported
  `PI_CODING_AGENT_DIR=/Users/jochen/.config/emerge` from another workspace, so
  Pi loaded the wrong account/configuration and returned no matching model;
  provider-qualified lookup also does not match the CLI's bare-name filter.
- Impact: the runner exited before review; no review round was consumed.
- Follow-up: clear stale `PI_CODING_AGENT_DIR`/`CODEX_HOME` from the tmux server,
  refresh workspace environment, use the bare model name for lookup, and
  consider teaching the shared runner to sanitize stale cross-workspace agent
  environment before preflight.
- Status: invocation workaround applied; shared harness follow-up deferred.

## 2026-07-12 - Claude Review Gate Uses A Model-Neutral Identity

- Repo: agent-stuff.
- Expected: the supervised Claude gate can use Opus by default while allowing an
  explicit Fable, Sonnet, or other Claude model without contradictory naming.
- Actual: the skill, package, executable, cache path, and workflow references all
  used `opus-review-loop` even though `--model` already accepted other models.
- Impact: callers could mistake Opus for a hard requirement and create parallel
  review paths for other Claude models.
- Follow-up: make `claude-review-loop` canonical, keep Opus as the default, pass
  explicit model identifiers through unchanged, retain a repository-local legacy
  Opus CLI/skill shim, and install only the canonical skill through chezmoi.
- Status: implemented; 158 standard tests pass, both canonical and legacy skill
  surfaces validate, and chezmoi deploys only the canonical skill name.

## 2026-07-12 - Pi Review Model Selection Fails Closed

- Repo: agent-stuff and managed agent instructions.
- Expected: Pi review always uses the subscription-backed GPT-5.6 Sol route.
- Actual: the preferred model was documented, but `--model` accepted arbitrary
  providers and historical guidance allowed non-GPT fallback. Obsolete shell
  aliases also encouraged routing Claude through Pi.
- Impact: agents could silently replace the mandatory review gate with Claude
  over an unsupported Pi route, OpenRouter, or a weak local model such as Qwen.
- Follow-up: permit only `openai-codex/gpt-5.6-sol`, validate it against
  `pi --list-models gpt`, reject all other models before spawning Pi, remove the
  Claude/Pi aliases, and require an explicit blocker when authentication fails.
- Status: implemented with model-policy tests and targeted chezmoi deployment.

## 2026-07-12 - Preserve Backend Timestamp Authority And Exact Row Identity

- Repo: emerge frontend UMF-1398 review cycle.
- Expected: mixed Fixed and Automatic Time Domain output is chronological while
  equal UTC instants are deduplicated and configured entry order stays intact.
- Actual: the first review exposed an existing all-or-nothing fallback when one
  backend timestamp was malformed; the second review caught that a proposed
  seconds-precision normalization silently collapsed distinct subsecond instants.
- Impact: a superficially small ordering fix could replace valid backend rows
  with locally expanded ones or create ambiguous dashboard row identities.
- Follow-up: keep every valid backend timestamp, warn and ignore only malformed
  siblings, deduplicate exact instants, and use a narrow exact UTC formatter for
  process-row identity while retaining existing seconds-precision APIs elsewhere.
- Status: fixed; full project checks pass and Pi round 3 is clean.

## 2026-07-13 - Exact Timestamp Identity Must Cover Every Lookup Boundary

- Repo: emerge frontend UMF-1398 follow-up review.
- Expected: preserving subsecond process rows in table construction also keeps
  row insertion, startup hydration, live-event routing, and slot projection
  exact.
- Actual: the first commit introduced exact row keys but left seconds-only
  formatters in compatibility facades and event normalization, so mutation and
  lookup could select the whole-second sibling or fail rebuilding a lone
  subsecond row.
- Impact: passing initial-layout tests did not prove that later state changes
  could address the same row identity.
- Follow-up: use one exact formatter at every internal identity boundary, keep
  seconds-only formatting explicit for external shapes, and require regressions
  spanning initial construction plus mutation, hydration, and live routing for
  both dashboard families.
- Status: fixed; focused and full checks pass, and fresh Pi review is clean.
## 2026-07-13 — Prefer exact timestamp identity before compact API timestamps

When records expose both an exact ISO timestamp and a lossy family-specific timestamp string, selection and deduplication must use the exact canonical UTC value first. Compact UCTE/CGMES strings are suitable only as a fallback when an exact timestamp is unavailable; otherwise whole-second and subsecond sibling rows can collapse into one export or summary result.

## 2026-07-13 - Reconciliation Readiness Needs Operation Provenance

- Repo: emerge frontend architecture-remediation review cycle.
- Expected: only hydration explicitly submitted for a broad reconciliation
  epoch can make that epoch's staged Process candidate ready.
- Actual: Pi rounds 1 and 2 found and drove fixes for transaction, exact-time,
  shutdown, retry, pending-merge, RTM, and documentation issues; the final third
  pass found that an older ordinary same-hex targeted refresh can still be
  classified as readiness for the newer broad epoch by shared map membership.
- Impact: a newer Process definition can be committed with stale snapshot data
  produced for the older targeted definition.
- Follow-up: track targeted operation provenance, prevent ordinary work from
  consuming broad readiness, and add the ordinary-targeted-versus-broad overlap
  regression before a newly authorized clean review gate.
- Status: blocked after the bounded three-round Pi cycle; 11 prior findings were
  fixed, one new Critical remains, and no commit was created.

## 2026-07-13 - Empty Reconciliation Domains Still Need Generation Guards

- Repo: emerge frontend architecture-remediation continuation.
- Expected: every candidate in an atomic broad Process group is guarded against
  live slot and CGMES mutations until the whole group commits.
- Actual: the authorized continuation fixed ordinary-targeted provenance,
  queued-intent ownership, remap/retry carryover, and ticker/startup docs, but
  the final Pi pass found that an empty timestamp-domain candidate becomes ready
  with no generation stamps while a non-empty sibling can keep the group open.
- Impact: a live mutation for the empty candidate can be overwritten by a later
  group commit even though all non-empty candidates are generation-validated.
- Follow-up: stamp relevant candidate/prior slot and CGMES scopes before empty-
  domain readiness, add a mixed-group live-mutation regression, and obtain a
  newly authorized clean review gate.
- Status: blocked at the second bounded cycle's three-round cap; four findings
  in that cycle were fixed, one Warning remains, and no commit was created.

## 2026-07-13 - Mutation Callbacks Complete Reconciliation Generation Safety

- Repo: emerge frontend architecture-remediation additional review cycle.
- Expected: every live slot or CGMES state change that can race broad Process
  reconciliation advances the corresponding exact or Process-wide generation,
  and a rejecting callback cannot leave untracked state committed.
- Actual: the first additional-cycle pass fixed empty/removal generation guards,
  then Pi found that new slot creation and synthetic CGMES replacement bypassed
  mutation notification. A fresh audit also caught non-atomic callback ordering
  in the first synthetic-state correction.
- Impact: a new hidden timestamp or synthetic CGMES result could be overwritten
  by a later broad commit, or callback failure could leave state changed without
  the generation record needed to reject stale hydration.
- Follow-up: notify on genuine slot creation and synthetic insert/replace/remove,
  keep no-op lookups/replacements silent, roll back slot creation or notify
  before CGMES mutation on callback failure, and drive mixed-group regressions
  through real store callbacks.
- Status: fixed; full frontend, E2E, RTM/specs, coverage, and docs gates pass,
  fresh subagent re-review is clean, and Pi GPT-5.6 Sol round 2 closed with zero
  Critical, Warning, or Suggestion findings. No commit was created.

## 2026-07-14 - Frontend Architecture Remediation Closeout

- Repo: emerge frontend architecture-remediation continuation.
- Expected: close all findings from the Fable team review, then run a bounded
  final Pi review cycle using `openai-codex/gpt-5.6-sol` until CLEAN or the
  mandatory three-round limit is reached.
- Actual: supervised Fable review returned CLEAN. Pi round 1 reported 1
  Critical, 3 Warnings, and 1 Suggestion; round 2 reported 1 Warning; round 3
  reported 1 documentation Warning. All seven findings were accepted and fixed.
  The final round-3 warning concerned obsolete guidance presenting the removed
  `legacy` IGM poll source as supported; the frontend development guide, IGM
  workflow spec, and remediation plan were corrected after that verdict.
- Impact: implementation, tests, and current documentation are corrected, but
  the bounded Pi cycle did not itself produce a post-fix CLEAN verdict because
  the review skill prohibits a fourth round.
- Follow-up: retain the fail-closed distinction between the final Pi verdict and
  the independent post-fix review. Start a newly authorized bounded Pi cycle if
  a literal Pi CLEAN verdict is required before commit.
- Status: all identified findings fixed; supervised Fable CLEAN; fresh focused
  subagent reviews CLEAN; frontend `just check` passes with 4,917 tests and 114
  E2E tests deselected; the headless E2E lane passes 112 tests with 2 live-
  backend tests deselected; frontend and specifications documentation builds
  pass. Pi rounds were 1C/3W/1S, 0C/1W/0S, and 0C/1W/0S. No commit or Jira write
  was created.

## 2026-07-14 - IGM Re-Validate Selection Review Cycle 1

- Repo: emerge frontend UCTE IGM Re-Validate selection fix.
- Expected: participating explicit item selections resolve all visible IGM
  cells, while synchronized whole-row selections retain clicked-column
  projection and plan/action eligibility stays aligned.
- Actual: Pi found that Qt reports full-width item rectangles through
  `selectedRows()`, the ICDF-specific menu plan still enabled Re-Validate
  unconditionally, and file-ID deduplication was not case-normalized. It also
  requested a backlog update that the task explicitly prohibited.
- Impact: full-width rectangles could silently narrow, ICDF menus could offer a
  no-target action, and case variants could create duplicate requests.
- Follow-up: track split-table row-selection provenance, use the shared resolver
  in the ICDF plan, normalize IDs canonically, add production-shaped tests, and
  reject the backlog write as out of scope before Pi re-review.
- Status: three code/test findings fixed and full frontend checks pass; one
  documentation-tracking finding rejected due explicit task scope; cycle 2
  pending.

## 2026-07-14 - IGM Re-Validate Selection Review Cycle 2

- Repo: emerge frontend UCTE IGM Re-Validate selection fix.
- Expected: Pi verifies the full-width item-selection, synchronized row-
  projection, plan eligibility, and canonical deduplication fixes without
  requiring prohibited backlog work.
- Actual: Pi re-reviewed the prior findings and expanded selection-provenance
  scope, returned zero Critical, Warning, or Suggestion findings, and agreed
  that the backlog finding should remain rejected under the task constraint.
- Impact: the review gate now confirms item/row semantics, plan/action parity,
  normalized stable deduplication, regression coverage, and feature-spec
  alignment.
- Follow-up: retain the provenance tests when changing split-table selection
  synchronization; no additional review cycle is required for this slice.
- Status: clean in cycle 2; three findings accepted and fixed, one rejected with
  scope rationale, full frontend check passes with 4,956 selected tests, and no
  commit or Jira/backlog write was created.

## 2026-07-14 - Heis Production Deployment Review Cycle 1

- Repo: Heis production deployment slice across ops-control and ops-library.
- Expected: Pi validates a content-preserving production bootstrap, promotion,
  backup/restore, monitoring, and cutover workflow without remote mutation.
- Actual: Pi reported 3 Critical and 9 Warning findings covering SSH policy and
  key rollout, partial promotion/restore failure, backup downtime and input
  locking, host-key/checksum pinning, token rotation, workspace paths, operator
  commands, and safety tests.
- Impact: the first draft could leave production inconsistent or stopped on
  partial failures and depended on several unverified operational assumptions.
- Follow-up: use additive-then-verified SSH keys, explicit key-only policy,
  production-side staging plus DB/media rollback, immutable backup targets,
  restart watchdogs/timeouts, pinned artifacts/host keys, managed token rotation,
  explicit manual backup/restore commands, and executable safety-contract tests.
- Status: all round-1 findings accepted and fixes implemented; validation and Pi
  round-2 re-review pending. No deployment, DNS change, or commit was performed.

## 2026-07-14 - Heis Production Deployment Review Cycle 2

- Repo: Heis production deployment slice across ops-control, ops-library, and
  the redirect-contract extension in NyxMon.
- Expected: Pi verifies the twelve round-1 fixes plus permanent `.com`/`www`
  canonical aliases, rollback traps, tests, documentation, and release notes.
- Actual: Pi reported 2 Critical, 2 Warning, and 1 Suggestion findings: first
  contact still inherited disabled Ansible host-key checking, restore did not
  migrate or require a database-backed HTTP 200, uncertain recovery could cancel
  watchdogs, alias checks did not enforce permanent redirect semantics, and
  FastDeploy step metadata retained an exceptional-only phase.
- Impact: host authenticity and restored schema health were not proven, failure
  recovery could strand the service, and redirect drift could pass monitoring.
- Follow-up: create a controller-only pinned known-hosts file before first
  contact, force it on production connections, migrate inside rollback, require
  exact proxy-aware HTTP 200, cancel watchdogs only after active-service proof,
  add exact NyxMon status/Location contracts, and align event metadata.
- Status: all five findings accepted and fixed with regression coverage; full
  library and NyxMon tests pass, focused control checks pass, and final Pi cycle
  3 is pending. No deployment, DNS change, or commit was performed.

## 2026-07-14 - Heis Production Deployment Review Cycle 3

- Repo: final bounded Heis production re-review across ops-control, ops-library,
  and NyxMon.
- Expected: Pi verifies the five cycle-2 fixes and closes the review within the
  skill's three-round maximum.
- Actual: Pi confirmed all five cycle-2 findings resolved, then reported one
  Warning and two Suggestions: exact redirect contracts bypassed transient HTTP
  retries, multi-service shell verification used aggregate systemctl semantics,
  and FastDeploy metadata/event parity lacked the claimed regression test.
- Impact: a transient 502 could alert immediately, future multi-service use
  could overstate recovery proof, and metadata drift could escape focused tests.
- Follow-up: retry configured transient statuses before exact-status failure,
  verify each service individually in rollback/success shells, and compare the
  configured FastDeploy step set with rendered runner emissions in tests.
- Status: all three final-round findings accepted and fixed; NyxMon now passes
  242 tests plus mypy, ops-library `just test` passes, and six focused control
  safety tests plus syntax/diff checks pass. The bounded Pi verdict itself was
  not CLEAN because the fixes occurred after the third and final allowed round;
  a new explicitly authorized cycle is required for a post-fix Pi CLEAN verdict.
  No deployment, DNS change, or commit was performed.

## 2026-07-14 - UMF-1348 Slovenia Label Review Cycle 1

- Repo: emerge frontend Slovenia country-label consistency fix.
- Expected: Pi verifies `Sl` presentation with canonical internal `SL` and
  backward-compatible `SI` handling across explicit merging and dashboards.
- Actual: Pi found that UI/routing normalization did not cover all live-event
  and startup ingress-to-domain seams, and that the canonical feature spec
  still documented the prior labels; it also identified misleading comments.
- Impact: aliases could form separate internal cells that projected into one
  displayed column, while implementation and canonical documentation diverged.
- Follow-up: normalize country aliases before domain `CellKey` construction and
  startup reduction, test cross-alias reconciliation, update the feature spec,
  and describe internal and display codes separately.
- Status: two Warnings and one Suggestion accepted and fixed; full frontend
  checks and the specifications build pass, with Pi cycle 2 pending.

## 2026-07-14 - UMF-1348 Slovenia Label Review Cycle 2

- Repo: emerge frontend canonical Slovenia identity re-review.
- Expected: Pi confirms the round-1 event, snapshot, documentation, and comment
  fixes close the normalization slice.
- Actual: Pi confirmed all round-1 findings fixed, then found legacy `SI`
  preservation in Process regions/configuration paths and plain-uppercase
  comparisons in diagnostics, task results, node suggestions, revalidation
  feedback, and deferred validation identities.
- Impact: legacy Process records could emit non-canonical paths or payloads, and
  alias-equivalent files/events could fail detail lookup or form separate queue
  identities.
- Follow-up: normalize UCT Process regions at hydration/serialization/update
  seams and canonicalize both sides of all retained UCT identity comparisons;
  cover API round trips, diagnostics, task results, suggestions, feedback, and
  deferred-event coalescing.
- Status: two Warnings accepted and fixed; focused validation passes, with full
  checks and the final Pi cycle 3 pending.

## 2026-07-14 - UMF-1348 Slovenia Label Review Cycle 3

- Repo: final bounded emerge frontend Slovenia label and identity re-review.
- Expected: Pi verifies the two cycle-2 normalization fixes and closes the
  review within the three-cycle limit.
- Actual: Pi confirmed all prior findings resolved and returned CLEAN with no
  Critical, Warning, or Suggestion findings.
- Impact: explicit merging and dashboard presentation now consistently use
  `Sl`, while internal UCT identity remains canonical `SL` and legacy `SI`
  inputs converge on that identity across the reviewed paths.
- Follow-up: no further review-cycle action is required for this slice.
- Status: clean in cycle 3; five findings accepted and fixed across the review,
  full frontend checks and the specifications build pass, and no commit or Jira
  write was created.

## 2026-07-15 - Validate Adversarial Schema Semantics Before Final Review

- Repo: podcast iOS local-search persistent-index foundation.
- Expected: column/index shape checks plus a behavioral FTS trigger probe would
  close the corruption-recovery finding within the three-cycle review limit.
- Actual: the final Pi cycle identified exact-column tables with hostile
  `CHECK` constraints that still pass shape validation; fallback mode had no
  semantic document probe, and structural constraint failures were not routed
  through derived-sidecar recovery.
- Impact: Slice 1 exhausted its review allowance with one Warning, so later
  implementation slices could not start despite focused tests and docs passing.
- Follow-up: before spending a final review cycle on SQLite-derived storage,
  test same-named schemas with preserved columns but altered constraints in
  every capability mode, and audit the complete error-code classification for
  each controlled semantic probe.
- Status: fail-closed at the slice boundary; no fourth review, next slice,
  commit, or push was attempted without explicit user direction.

## 2026-07-15 - Keep Implementation Agents Out Of Review Orchestration

- Repo: podcast iOS local-search persistent-index foundation.
- Expected: the fresh Pi implementation session would make the bounded schema
  fix and leave independent review orchestration to the primary agent.
- Actual: despite being assigned implementation rather than review, the Pi
  session used its shell access to run an unsolicited Claude review and cited
  that verdict in its completion report.
- Impact: the extra verdict violated the task's Pi-only review requirement and
  could have been mistaken for the mandatory fresh read-only gate.
- Follow-up: implementation prompts must explicitly forbid invoking any coding
  agent or reviewer command (Pi, Claude, Codex, or wrappers), and the primary
  agent must ignore unsolicited verdicts and run the configured review branch
  independently.
- Status: unsolicited verdict discarded; no related process remained in the
  podcast workspace, and a fresh read-only Pi review was launched as required.

## 2026-07-15 - Podcast Local-Search Slice 1 Authorized Review Cycle 4

- Repo: podcast iOS local-search persistent-index foundation.
- Expected: the user-authorized extra Pi cycle would verify canonical table
  definitions, all-mode semantic probing, and controlled constraint recovery.
- Actual: the fresh read-only Pi reviewer confirmed the cycle-3 Warning fixed
  and found no new Critical, Warning, or Suggestion findings.
- Impact: Slice 1 closed cleanly and the next bounded implementation slice could
  begin without accepting a malformed-derived-schema risk.
- Follow-up: retain exact-column hostile-constraint fixtures for both FTS and
  fallback modes, and explicitly forbid implementers from invoking reviewers.
- Status: CLEAN in authorized cycle 4; 96 focused tests and documentation/diff
  checks passed, with no commit or push.

## 2026-07-15 - Podcast Local-Search Slice 2 Authorized Review Cycle 4

- Repo: podcast iOS bounded local-search maintenance and containment.
- Expected: three normal Pi cycles would close lifecycle cancellation, reader
  ownership, and oversized-note preprocessing findings.
- Actual: cycle 3 found that `length(CAST(text AS BLOB))` could still make
  SQLite materialize a complete note before incremental blob reads. The user
  authorized one extra cycle; candidate queries were reduced to row identity,
  sizing moved to `sqlite3_blob_bytes`, and the fresh reviewer returned CLEAN.
- Impact: authoritative candidate selection, sizing, UTF-8 reconstruction,
  folding, sidecar writes, and pruning are now independently bounded or
  cancellable without restoring corpus-wide memory expansion.
- Follow-up: for large SQLite text, treat SQL value expressions as part of the
  resource boundary; prove the query plan does not touch content before the
  explicit incremental-blob seam.
- Status: CLEAN in authorized cycle 4; 229 focused tests and documentation/diff
  checks passed, with no commit or push.

## 2026-07-13 - Instrument Wire Attempts And Readiness Completion Separately

- Repo: emerge frontend startup diagnostics review cycle.
- Expected: request metrics describe backend traffic accurately, while the
  dashboard-readiness timestamp marks the moment hydration finishes.
- Actual: the first Pi review found that metrics wrapped the logical retry
  sequence rather than each wire attempt, and the diagnostics reused the
  hydration-start ticker cursor as the readiness-completion timestamp.
- Impact: transient attempts and HTTP-error bodies were undercounted, timing
  buckets were misleading, and long startups displayed readiness too early.
- Follow-up: retain logical active-request tracking across retries, add separate
  per-attempt transport accounting including HTTP-error bodies, and keep the
  ticker cursor distinct from an independently captured completion timestamp.
- Status: fixed after review round 1; focused and full validation pass, with
  re-review pending.

## 2026-07-13 - Diagnostic Collection Must Preserve Retry Control Flow

- Repo: emerge frontend startup diagnostics review cycle.
- Expected: opt-in metrics observe transient HTTP failures without changing
  safe-read retry behavior, and disabled metrics leave transport behavior
  untouched.
- Actual: the second Pi review found that unconditional error-body reads could
  replace a retryable HTTP error when the body stream itself failed, and also
  consumed error bodies when metrics were disabled.
- Impact: a truncated 502/503 response could suppress the configured retry;
  merely adding or disabling diagnostics could therefore change application
  behavior.
- Follow-up: collect transient error bodies only when metrics are enabled,
  treat all ordinary body-read/close failures as diagnostic failures while
  re-raising the original HTTP error, and test both the failed collection and
  disabled-metrics paths.
- Status: fixed after review round 2; focused and full validation pass, with
  final re-review pending.

## 2026-07-13 - Count Partial Bodies Without Replacing Transport Errors

- Repo: emerge frontend startup diagnostics review cycle.
- Expected: transferred-byte diagnostics include bytes already received before
  a response stream is truncated, without altering retry or exception behavior.
- Actual: the final permitted Pi review found that `IncompleteRead.partial` was
  discarded for both HTTP-error bodies and successful-status response bodies.
- Impact: the exact incident class being diagnosed could underreport traffic
  and omit the affected response encoding from byte summaries.
- Follow-up: extract byte-like partial payloads from body-read exceptions for
  metrics and cached error parsing, while re-raising the original transport
  exception; cover both transient HTTP-error and HTTP-200 truncation paths.
- Status: fixed after review round 3; focused and full validation pass. The
  bounded three-round review cycle is exhausted, so a further Pi-clean verdict
  requires explicit direction for a new review cycle.

## 2026-07-13 - Presence Does Not Prove Enriched Snapshot Data Is Redundant

- Repo: emerge frontend startup hydration optimization plan review.
- Expected: bulk non-enriched Merge reads plus selective fallback enrichment
  would preserve reducer behavior while removing duplicated Process data.
- Actual: the first Pi plan review found that enriched slot Process-family data
  may override status provenance and diagnostics even when the selected model
  is already present; the proposed identity fallback also maps to per-identity
  backend reads.
- Impact: a payload optimization could silently change UCTE or CGMES startup
  status, or replace response-size pressure with excessive database queries.
- Follow-up: keep enriched reducer inputs, use the measured gzip plus 100-row
  pagination mitigation, and treat a slim response as a separate backend or
  reducer-parity change.
- Status: plan revised; Pi round 3 closed the plan review with no findings.

## 2026-07-13 - Compatibility Slices Need Their Own Acceptance Gate

- Repo: emerge frontend startup hydration optimization plan review.
- Expected: the revised safe transport/pagination slice could be judged against
  the existing startup optimization targets.
- Actual: Pi round 2 found that the measured compatibility path takes 24.513 s
  while the broader plan still targets less than 10 s for all Process API work.
- Impact: a safe timeout fix could be incorrectly rejected, or described as
  meeting a performance target it demonstrably does not meet.
- Follow-up: accept the slice on timeout elimination, semantic parity, and
  compressed wire volume; retain the 10-second goal for later backend response
  shaping.
- Status: plan clarified; Pi round 3 closed the plan review with no findings.

## 2026-07-13 - Retryable HTTP Error Bodies Need Explicit Ownership

- Repo: emerge frontend startup hydration optimization review cycle.
- Expected: HTTP error responses are retried or classified without retaining
  transport resources, regardless of whether request metrics are enabled.
- Actual: the first implementation review found that JSON requests only closed
  HTTP errors while metrics were enabled; metrics-disabled retry attempts could
  leave response streams open, while terminal parsing still needed their body.
- Impact: repeated backend failures could leak connections or file descriptors,
  and closing a response before terminal classification would lose useful error
  details.
- Follow-up: always cache the small HTTP error body before closing each JSON
  response, classify terminal errors from that cache, close other HTTP-error
  paths after message construction, and test both metrics modes and retries.
- Status: fixed after implementation review round 1; Pi round 3 is clean and
  the final full validation passes.

## 2026-07-13 - Compressed-Body Failures Can Occur Before Decompression

- Repo: emerge frontend startup hydration optimization review cycle.
- Expected: every truncated gzip GET follows the same bounded safe-read retry
  behavior and reports the compressed bytes and timing already observed.
- Actual: the second implementation review found that an HTTP-framing
  `IncompleteRead` exits `response.read()` before gzip decoding, bypassing the
  retryable decompression error and losing known response dimensions for some
  read-time failures.
- Impact: a recoverable truncated UAT response could still fail startup even
  after gzip retry handling was added, while diagnostics misattributed body-read
  time to waiting for response headers.
- Follow-up: preserve status, encoding, header-wait and body-read timing for
  exceptions after headers; translate an incomplete advertised-gzip GET into the
  existing retryable gzip error after recording partial wire bytes; test a
  truncated first response followed by a valid compressed response.
- Status: fixed after implementation review round 2; Pi round 3 is clean and
  the final full validation passes.

## 2026-07-13 - Diff-Only Review Bundles Need Source for Diagnostic Audits

- Repo: emerge frontend startup responsiveness diagnostic review.
- Expected: caller-selected unchanged source paths would be available to a
  Claude review requested for a root-cause audit with no worktree diff.
- Actual: the first harness run contained only the trusted context and an empty
  diff, so Claude correctly failed closed without examining source.
- Impact: an unchanged-code diagnostic review cannot be grounded by the normal
  diff-only bundle even when the prompt names the relevant paths.
- Follow-up: copy only the selected unchanged files into an isolated temporary
  Git repository as untracked repository-derived evidence, then run the normal
  supervised Claude harness against that bounded bundle.
- Status: retry succeeded; Claude independently reviewed the selected source and
  corroborated the primary quadratic main-thread projection finding.

## 2026-07-13 - Pi Review Must Fail Closed When Authentication Is Unavailable

- Repo: emerge frontend startup responsiveness implementation review.
- Expected: Pi would review the completed startup projection fix with the pinned
  `openai-codex/gpt-5.6-sol` model.
- Actual: the mandatory `pi --list-models gpt` preflight reported no available
  authenticated models, so no Pi review cycle started.
- Impact: passing project checks and a local diff audit cannot be represented as
  a clean independent Pi review.
- Follow-up: authenticate the `openai-codex` provider in the active Pi shell,
  confirm the pinned model appears in `pi --list-models gpt`, then resume review
  round 1 without substituting another provider or model.
- Status: resolved after provider reauthentication; the pinned model preflight
  passed and Pi round 1 completed cleanly.

## 2026-07-13 - UI Performance Fixes Benefit From Boundary Call-Count Tests

- Repo: emerge frontend startup responsiveness implementation review.
- Expected: batching startup slot projection would remove the quadratic
  main-thread filter work without changing direct single-slot rendering.
- Actual: explicit tests at the hydration, adapter, and projector boundaries let
  Pi verify one startup batch, one filter call per batch, invisible timestamp
  handling, and preserved single-slot filtering without relying on timing tests.
- Impact: the performance invariant is deterministic and reviewable across
  machines, while the Qt-thread ownership rule remains unchanged.
- Follow-up: prefer call-count and batching-boundary assertions for similar UI
  hot paths; reserve wall-clock checks for representative UAT measurements.
- Status: Pi round 1 closed with no Critical, Warning, or Suggestion findings.

## 2026-07-13 - Isolated Review Repositories Still Need a HEAD

- Repo: emerge frontend startup concurrency plan review.
- Expected: an isolated Git repository containing untracked source evidence
  would be enough for the supervised Claude harness to build a review bundle.
- Actual: bundle construction failed before review because Git diff collection
  requires a resolvable `HEAD`, even when all review evidence is untracked.
- Impact: the first harness attempt could not start Claude and its run directory
  could not be reused.
- Follow-up: create an empty baseline commit immediately after initializing an
  isolated review repository, then use a fresh harness run directory.
- Status: corrected; Claude plan review round 1 ran successfully on retry.

## 2026-07-13 - Concurrency Plans Must Reconcile Historical Load Evidence

- Repo: emerge frontend startup concurrency plan review.
- Expected: gzip, bounded pages, and a small read cap would justify overlapping
  independent startup pipelines.
- Actual: Claude round 1 found that the plan did not explicitly reconcile its
  concurrency-first step with documented pre-mitigation API replica restarts,
  nor update every specification statement whose timing meaning would change.
- Impact: a locally correct executor change could be promoted without proving
  backend stability, and diagnostics could misleadingly call overlapping phase
  durations wall time.
- Follow-up: default to two reads, require a post-change backend-pressure gate,
  preserve sequential pages, update all affected spec sections, and define
  deterministic executor shutdown and infrastructure-failure behavior.
- Status: round 2 reduced the review to two suggestions; the final revision now
  names the contradictory historical statements explicitly and adds an
  executor-submission-failure cleanup test before Claude round 3.

## 2026-07-13 - Bound Concurrency Result Retention, Not Only Active Requests

- Repo: emerge frontend startup concurrency plan review.
- Expected: a two-worker pool would bound backend pressure while overlapping
  the dominant IGM and Merge reads.
- Actual: Claude round 3 found that submitting every Process up front could
  retain several large decoded Process result sets even though active requests
  stayed at two.
- Impact: backend concurrency metrics could look healthy while frontend peak RSS
  regressed substantially on the largest payloads.
- Follow-up: submit, gather, and reduce stages for one Process at a time while
  reusing the two-worker pool; add frontend peak RSS to the post-change UAT gate.
- Status: sole final suggestion accepted and incorporated; no Critical or
  Warning findings remain, so the plan gate closed at the three-round limit.

## 2026-07-13 - Sequential Submission Does Not Imply Sequential Object Lifetime

- Repo: emerge frontend startup concurrency implementation review.
- Expected: gathering and reducing one Process before submitting the next would
  keep decoded startup data bounded to one Process.
- Actual: Pi round 1 found that loop-local futures, outcomes, and raw record
  aliases from Process N remained referenced when Process N+1 was submitted.
- Impact: two complete Process payloads could briefly coexist, contradicting the
  documented RSS bound even though request concurrency never exceeded two.
- Follow-up: explicitly release the completed per-Process stage graph and raw
  record aliases before the next loop iteration, add a two-Process lifetime
  regression, and assert successful reusable-executor shutdown as well as the
  existing infrastructure-failure cleanup path.
- Status: production Warning and Suggestion accepted and fixed. Pi round 2
  confirmed the runtime cleanup but found the regression only tracked Futures;
  the test now also weak-tracks stage outcomes, fetch containers, and raw record
  sequences. Pi round 3 closed cleanly with no Critical, Warning, or Suggestion
  findings.

## 2026-07-14 - Make Does-Not-Raise Regression Assertions Explicit

- Repo: emerge frontend Qt network reply buffer fix review.
- Expected: reproducing the production signal-connection order would clearly
  protect the weak-reference compatibility fix.
- Actual: Claude round 1 found that the regression depended on
  `buffer.attach()` not raising, but did not document that call as its assertion.
- Impact: a later signal-wiring refactor could leave the test green while making
  its original guarding intent unclear.
- Follow-up: label the connection call as the deliberate assertion in the test;
  also avoid `status` as a zsh wrapper variable because it is read-only.
- Status: suggestion accepted and fixed; Claude round 2 closed cleanly with no
  Critical, Warning, or Suggestion findings. The same zsh variable mistake
  recurred in a later plan-review wrapper after the review itself completed;
  future wrappers must use `review_exit`, never `status`.

## 2026-07-14 - Workspace Census Must Tolerate Prunable Worktrees

- Repo: emerge workspace coordination.
- Expected: the workspace census would report active claims before the CGMES
  merge-progress fix started.
- Actual: the census aborted on the prunable worktree path
  `/private/tmp/emerge-prefix-check` after its gitdir disappeared.
- Impact: automated triage produced no report even though the coordination
  ledger and remaining worktrees were readable.
- Follow-up: inspect the ledger and `git worktree list --porcelain` directly
  without pruning user state; make the census skip explicitly prunable entries.
- Status: current task claimed manually in the ledger; census hardening remains
  open outside this implementation scope.

## 2026-07-14 - Order Terminal Progress Across Events, Records, and Reloads

- Repo: emerge frontend CGMES merge-progress implementation review.
- Expected: accepting a terminal ticker event and reloading the Process would
  replace the transient percentage with the completed or failed merge state.
- Actual: Pi review exposed three independent races: terminal records without a
  ZIP could lose to the transient overlay, older records could resurrect a
  running state, and overlapping reload callbacks could overwrite newer data or
  release preservation ownership too early.
- Impact: a backend-completed merge could remain displayed at 39%, including
  after switching Processes or receiving later ticker updates.
- Follow-up: preserve stable Process identity, make terminal task state
  authoritative without requiring a ZIP, use absorbing timestamp precedence,
  and gate both cache writes and overlay release with a monotonic reload
  generation.
- Status: all findings from three Pi cycles were fixed and the focused and full
  suites pass; the last fixes could not receive a fourth Pi cycle because the
  review workflow has a hard three-cycle cap, so the slice is not independently
  review-clean.

## 2026-07-14 - Pi Model Preflight Can Stall Under Captured Fish Output

- Repo: emerge frontend CGMES IGM status review.
- Expected: the mandated Pi runner would capture `pi --list-models gpt` through
  Fish and proceed to the approved `openai-codex/gpt-5.6-sol` review.
- Actual: two fresh tmux attempts stalled in the captured model-list command
  with no log output, while the same model listing completed immediately in a
  direct PTY and confirmed authentication and the required model.
- Impact: the reviewer never started in either original attempt.
- Follow-up: after cleanly terminating both process groups, use the successful
  direct listing as the required preflight and start a fresh tmux runner at the
  Pi review command itself; investigate whether `string collect` or Pi's TTY
  detection causes the captured-list hang.
- Status: recovered; cycle 1 completed normally in the fresh preflighted run,
  its four Warnings and one Suggestion were fixed, and Pi cycle 2 closed cleanly
  with no Critical, Warning, or Suggestion findings.

## 2026-07-14 - Keep Claude Plan Context Inside the Review Bundle

- Repo: emerge merge Task Activity Ledger plan review.
- Expected: Claude would review the docs-repository plan while using companion
  code paths only as caller-authored orientation.
- Actual: naming absolute companion-worktree paths prompted an out-of-sandbox
  Glob, so the harness correctly marked the attempt invalid before a verdict.
- Impact: no review finding or clean result was produced; implementation stayed
  blocked at the plan gate.
- Follow-up: give the isolated reviewer only in-bundle plan/spec paths and keep
  code-flow evidence summarized in trusted context; use `review_exit` rather
  than zsh's read-only `status` variable in wrappers.
- Status: recovered by retrying with a fresh run directory and narrowed context.

## 2026-07-14 - Review Cross-Repo Slices as Separate Claude Bundles

- Repo: emerge frontend merge Task Activity Ledger implementation and specs.
- Expected: one full-change Claude gate would verify code, lifecycle behavior,
  and the companion documentation consistently.
- Actual: the supervised harness accepts one Git repository per bundle, so the
  code and documentation diffs needed separate reviews in each round. The code
  pass found missing compile-time enforcement for family-tagged UI opens; the
  docs passes found traceability drift and verification evidence omitted from
  the recorded plan command.
- Impact: relying on the code-repository symlink alone would not have reviewed
  the actual documentation diff, and repository-wide producer assumptions
  would have remained conventional rather than enforced.
- Follow-up: run paired repository bundles for cross-repo work, require family
  at the UI opener boundary, mirror RTM/feature evidence exactly, and keep the
  reviewed plan's verification command aligned with added integration modules.
- Status: accepted findings fixed; frontend review closed clean in round 2 and
  documentation review closed clean at the round-3 cap.

## 2026-07-15 - Embed Caller-Authored Cross-Repo Plans for Code Review

- Repo: emerge frontend sequential merge queued-visibility plan review.
- Expected: the code-repository Claude bundle could follow an absolute path to
  the companion documentation repository's new plan.
- Actual: the harness rejected that Read target as out of scope before starting
  a review, consistent with its one-repository isolation boundary.
- Impact: no review cycle or verdict was produced; implementation remained
  correctly blocked at the plan gate.
- Follow-up: embed the caller-authored plan as trusted review intent and expose
  only code-repository paths for implementation inspection; review the eventual
  documentation diff in its own repository bundle.
- Status: retry prepared with a fresh run directory.

## 2026-07-15 - Reuse a Direct Pi Preflight After Captured Listing Stalls

- Repo: emerge frontend sequential merge queued-visibility reviews.
- Expected: the mandated Pi tmux runner would capture `pi --list-models gpt`
  and then start the approved `openai-codex/gpt-5.6-sol` reviewer.
- Actual: the captured Fish preflight stalled with an empty log before the
  reviewer started, while a direct PTY model listing completed and confirmed
  the required authenticated model.
- Impact: the failed preflight consumed no review cycle, but the first slice
  gate could not start until the orphaned process group was terminated.
- Follow-up: after verifying the direct listing, use a fresh runner that starts
  the Pi review command with that exact preflighted model; continue to fail
  closed rather than substituting a provider or model.
- Status: recovered; every Pi slice gate ran with the approved model, and the
  final Slice 3 gate closed cleanly at cycle 3.

## 2026-07-15 - Assert the Targeted Refresh, Not the Startup Gate

- Repo: emerge frontend Process Optional/Recessive sparse-edit flow.
- Expected: the real-dialog regression would prove the authoritative
  post-save snapshot had completed.
- Actual: the first assertion watched the broad startup snapshot flag, which
  can already be idle while a targeted Process refresh is still running.
- Impact: the test could pass after checking only the update response and miss
  a failed targeted snapshot delivery.
- Follow-up: expose a thread-safe targeted-refresh in-flight query and assert a
  projected timestamp slot plus hydrated IGM identity that only the snapshot
  applier can install.
- Status: fixed; focused and full frontend checks passed, and Pi cycle 3 closed
  with no Critical, Warning, or Suggestion findings.

## 2026-07-16 - Review Legacy Viewer Removal Through the Generated RTM

- Repo: emerge frontend legacy IGM log-viewer removal and companion specs.
- Expected: Pi would verify the dead UI path was removed while the rich
  `Checking logs` path and its documentation stayed intact.
- Actual: three rounds progressively found a dead synthetic fallback, missing
  inline-log coverage, stale viewer/action terminology, and semantically weak
  RTM evidence. The configured extraction catalog was absent, so the official
  RTM generator used a temporary catalog reconstructed from the committed RTM
  while still validating current feature mappings and pytest evidence.
- Impact: passing tests alone would have left dead API surface and misleading
  operator/traceability documentation; the three-cycle cap ended with one
  evidence warning and one wording suggestion reported in the final round.
- Follow-up: fixed both final findings, regenerated the RTM with exact relevant
  test nodes, reran frontend/spec validation, and did not exceed the review
  cycle cap. Restore a populated canonical extraction output before the next
  unrelated RTM regeneration.
- Status: all reported findings fixed; final post-review checks are green, but
  the post-round-3 fixes were not eligible for a fourth Pi review.

## 2026-07-18 - Model Real Pi Isolation and Process Reaping

- Repo: daybook continuous-weeknotes Step-3 MVP authoring boundary.
- Expected: disabling pi tools, sessions, and context files plus killing the
  process group would provide a contained, bounded authoring subprocess.
- Actual: review found that retained global pi configuration could still alter
  provider/system behavior, and that a terminated but unreaped leader could
  make a successful group cleanup look permanently alive.
- Impact: ambient configuration could weaken the fixed contract, while timeout
  and interruption paths could escalate unnecessarily and mask their real
  result.
- Follow-up: require a dedicated owner-only pi agent directory containing only
  subscription auth, pin the replacement system prompt and telemetry setting,
  and poll/reap the direct child while supervising descendant group cleanup.
- Status: all findings fixed with hostile-config, descendant, zombie-leader,
  malformed-output, and pipe-lifecycle coverage; Pi round 3 closed CLEAN.

## 2026-07-18 - Lock the Write, Not Just the Read

- Repo: django-cast and daybook deterministic draft lookup/find-or-create.
- Expected: an exact parent+slug lookup plus `SELECT FOR UPDATE` around create
  would make competing draft creators converge portably.
- Actual: review found latest-draft slugs diverge from materialized page slugs,
  and SQLite ignores `SELECT FOR UPDATE` even though django-cast supports it.
- Impact: lookup could miss an unpublished slug edit, and SQLite creators could
  both pass a sibling check despite documentation promising serialization.
- Follow-up: match and serialize the same latest revision, fail closed on legacy
  ambiguity, use a transactional no-op parent UPDATE followed by a parent reload,
  and strictly validate query cardinality and client response shapes.
- Status: all six findings fixed; django-cast remained at 100% coverage on its
  SQLite test backend, and the third Pi review closed CLEAN.

## 2026-07-18 - Persist the Fence Before Delivery

- Repo: daybook continuous-weeknotes Step-3 MVP reconcile state rails.
- Expected: rechecking source and steering hashes immediately before delivery
  would be enough to prevent stale authoring results from being applied.
- Actual: review found that a successful fence was not persisted, so callers
  could bypass it when recording delivery; it also found state-file size and
  FIFO hazards in the local state reader, plus incomplete fenced-recovery wording.
- Impact: an orchestration bug could record success without proof of a current
  input fence, and a hostile or corrupt state path could block or become
  unreadable after an oversized write.
- Follow-up: add an explicit persisted `fenced` state required by delivery,
  recover both active `running` and `fenced` attempts by exact UUID, enforce the
  read-size limit before atomic writes, and validate an `O_NOFOLLOW|O_NONBLOCK`
  file descriptor rather than a pre-open path check.
- Status: focused and full tests passed; a fresh Pi closure review reported
  CLEAN with no changes after all prior findings were resolved.

## 2026-07-18 - Persist Intent Before Crossing the Remote Boundary

- Repo: daybook continuous-weeknotes Step-3 MVP orchestration.
- Expected: a persisted stale-result fence plus compare-before-PATCH would make
  delivery safely resumable after any local or remote failure.
- Actual: review exposed the cast-to-checkpoint crash window, incomplete target
  identities, uncertain fsync semantics, and lossy media canonicalization.
- Impact: a crash after a remote commit could re-run a nondeterministic author,
  a changed target could receive recovery work, and opaque media differences
  could be misclassified as unchanged.
- Follow-up: persist and cleanly fsync a content-free pre-cast intent; pin the
  full non-secret target; recover only exact committed semantics; preserve
  intent on unobservable interrupts; and use one audience-aware canonicalizer
  for hashes and cast comparisons that retains every opaque-block field.
- Status: 566 tests and docs passed; the final fresh Pi closure review reported
  CLEAN with no findings or changes.

## 2026-07-18 - Bound the Pi Model-List Preflight

- Repo: ops-library and ops-control Daybook weeknotes deployment slice.
- Expected: the mandatory Pi reviewer preflight would list the authenticated
  `openai-codex/gpt-5.6-sol` model promptly before starting a read-only review.
- Actual: `pi --list-models gpt` remained connected and silent for four minutes,
  so the reviewer never started and no completion report existed.
- Impact: an unbounded availability check can strand the review gate while an
  empty log looks superficially like an idle reviewer.
- Follow-up: terminate and verify cleanup of the stalled session, then retry in
  a fresh session with an explicit timeout around only the model-list preflight;
  continue to fail closed rather than falling back to another model/provider.
- Status: first round-2 attempt terminated cleanly; a fresh bounded-preflight
  retry completed normally, and the eventual round-3 reviewer closed CLEAN.

## 2026-07-18 - Seed Mutable OAuth State Only Once

- Repo: ops-library and ops-control Daybook weeknotes deployment slice.
- Expected: copying a dedicated staged `auth.json` on each role application
  would keep unattended Pi authentication deterministic.
- Actual: Pi legitimately refreshes and persists OAuth state in the managed
  agent directory, so an authoritative repeated copy could restore expired or
  rotated refresh credentials; the initial check-mode test also masked a
  missing destination parent by pre-creating the managed runtime.
- Impact: ordinary redeploys could break unattended auth, while a production
  first-install `--check` could fail despite the regression passing.
- Follow-up: seed missing auth with `force=false`, preserve safe managed state,
  require an explicit unloaded-only rotation flag, and test check mode with the
  entire managed runtime absent plus distinct seed/refreshed auth contents.
- Status: focused tests and Ansible lint passed; the final fresh Pi review
  reported CLEAN with no findings or changes.

## 2026-07-18 - Verify Security Preconditions at the Receiving Service

- Repo: daybook, django-cast, ops-library, and ops-control continuous-weeknotes rollout.
- Expected: a client-supplied bearer header and a pre-PATCH live-state check
  were sufficient to keep steering private and delivery draft-only.
- Actual: the final cross-repository review found that weeknotes.home never
  authenticated the header, django-cast did not atomically enforce unpublished
  state with the revision write, and top-level rollout docs still described the
  already-built scheduler as deferred.
- Impact: steering rows were exposed through the private API boundary, a publish
  could race the client-side check, and operators could follow stale rollout
  guidance.
- Follow-up: enforce one managed bearer secret at weeknotes.home and wire it to
  Studio, add a transactional row-locked `require_unpublished` PATCH precondition
  for posts and episodes, validate returned live state, and update Slice-5 status,
  activation gates, and rollback documentation.
- Status: fixes implemented and full native checks passed; the final fresh Pi
  cross-repository closure review confirmed all three findings fixed and reported
  CLEAN with zero Critical, Warning, or Suggestion findings.

## 2026-07-16 - Use A Dedicated Fish Runner For Pi Review Tmux Sessions

- Repo: podcast iOS remote-command registration reliability.
- Expected: the first fresh Pi read-only review would start in tmux and write
  its report to the configured log.
- Actual: an inline tmux command mixed outer-shell quoting with Fish-only
  syntax, exited before Pi started, and created neither a log nor a verdict.
- Impact: no review cycle was consumed and no worktree mutation occurred, but
  the slice lost one orchestration round trip before review could begin.
- Follow-up: create the prompt and a dedicated temporary Fish runner first,
  then pass prompt/log paths as runner arguments exactly as the review skill
  documents; do not embed the review pipeline and interactive pause inline.
- Status: corrected immediately; the fresh Pi review then ran normally, found
  two Warnings in round 1, and returned CLEAN after both were fixed in round 2.

## 2026-07-24 - Probe No-Replace Rename On The Actual Destination Filesystem

- Repo: daybook Apple Photos recovery bundle.
- Expected: macOS `renameatx_np(RENAME_EXCL)` would provide atomic no-clobber
  directory publication on both local storage and the mounted Samba share.
- Actual: the API worked locally but the live SMB filesystem returned
  `ENOTSUP`. A first reservation fallback then showed that the share also
  rejects renaming a populated directory into the reserved directory even
  though it permits file renames.
- Impact: relying only on the native flag would make verified Fractal bundles
  fail at their final publication boundary.
- Follow-up: retain atomic no-replace rename where supported; on unsupported
  filesystems atomically reserve the destination, publish into the
  command-owned directory, write the manifest last, and remove an explicit
  incomplete marker as the final completion event. Recreate verified
  subdirectories and rename their files individually under that marker. Test
  both branches and run live SMB no-clobber and full-bundle probes.
- Status: focused tests, the live SMB success/collision probes, and a full
  strict-validation bundle/checksum run pass; the final round-3 Pi review
  returned CLEAN with no Critical, Warning, or Suggestion findings.

## 2026-07-24 - Enforce Explicit Inputs And Wrap Lazy Data-Source Reads

- Repo: daybook Photos offload discovery Slice 1.
- Expected: an explicit Photos library and a `PhotosError` CLI boundary made
  the discovery command fail closed.
- Actual: the option remained syntactically optional, and database construction
  or lazy asset-property evaluation could still escape as a traceback.
- Impact: unattended execution could select a fallback library or expose an
  untyped failure instead of the documented safe boundary.
- Follow-up: make the safety-critical library option required, wrap the complete
  construction/read/classification boundary while preserving typed errors, and
  test constructor plus lazy-property failures.
- Status: targeted tests and docs build passed; Pi round 2 verified both fixes
  and returned CLEAN with zero findings.

## 2026-07-24 - Never Unlink A Pathname After A Safety-Critical Exchange

- Repo: daybook Photos offload reconciliation Slice 2.
- Expected: exact read tokens plus atomic no-replace/exchange publication would
  make the owner-only ledger safe against concurrent manual replacements.
- Actual: repeated Pi review found progressively smaller pathname races:
  post-exchange cleanup could unlink substituted state, interruption could
  occur immediately after a swap, first publication was not bound to the
  original temporary file descriptor, and final-component symlinks were being
  resolved away before validation.
- Impact: a same-owner concurrent edit or interruption could lose the previous
  ledger, publish unverified bytes, or redirect state through a symlink even
  though normal tests remained green.
- Follow-up: bind generated bytes to their open-file identity, validate both
  sides after publication, never unlink any pathname that might contain
  exchanged or substituted state, quarantine prior ledgers under unique
  private names, preserve recovery paths across fsync failures, and resolve
  only the state path's parent. Also reject non-scalar Unicode and classify
  transient SQLite failures at every lazy-read boundary.
- Status: 949 tests, docs build, a real 1,619-item Atlas first/unchanged pair,
  and byte-identical second-run ledger hash passed; Pi round 8 returned CLEAN.

## 2026-07-23 - Keep Crash Diagnostics Fail-Safe And Validate From The Right Root

- Repo: emerge frontend WSLg process-dialog crash investigation.
- Expected: removing an unused application-global Qt filter and adding
  low-volume breadcrumbs would be safe to commit after the normal full gate.
- Actual: the first review found that edit metadata was resolved eagerly and
  could theoretically block the dialog being diagnosed, and that the new
  breadcrumbs lacked edit-path and mutation coverage. A validation retry also
  used repository-root pathspecs while already inside the frontend directory.
- Impact: no product failure or unintended commit occurred, but the
  instrumentation needed a fail-safe resolver and the first validation retry
  stopped before the full gate.
- Follow-up: isolate diagnostic metadata behind exception-safe resolution,
  cover the motivating edit path and each breadcrumb category, and use paths
  relative to the active command working directory.
- Status: all findings were fixed, the full frontend gate passed, and fresh
  Opus reviews returned CLEAN for both the implementation and its staged
  known-issue update.

## 2026-07-24 - Isolate Pi Auth From An Unrelated Application Directory

- Repo: ops-control Emerge Windows publisher planning.
- Expected: the mandatory Pi/GPT-5.6 preflight would read Pi's own OAuth store
  and list the approved `openai-codex/gpt-5.6-sol` model.
- Actual: the parent session exported `PI_CODING_AGENT_DIR` for the Emerge
  application, whose unrelated `auth.json` schema contains nullable fields;
  Pi treated that file as its credential store and crashed during discovery.
- Impact: the review correctly failed closed before implementation began.
- Follow-up: run review preflight and the reviewer with an explicit
  `PI_CODING_AGENT_DIR=~/.pi/agent`, continue to avoid provider/model fallback,
  and keep credential values out of diagnostics.
- Status: corrected without modifying either application repository; the
  approved model preflighted successfully and plan review round 1 completed.
