# Review Cycle And Agent Workflow Log

Status: active log

## 2026-10-06 — Redact age keys, Token/Basic auth and credential files

A probe of the shared redaction (`claude_review_loop/redact.py`, used by all
three review harnesses) showed that age secret keys, `Authorization: Token` and
`Authorization: Basic` header values, Slack webhook URLs and Mailgun keys
reached the bundle unchanged. Files such as `.git-credentials`, `.pgpass`,
`.npmrc`, `keys.txt`, `credentials.json`, `*.pfx` and `*.kdbx` were not treated
as secret, so the diff showed them and the reviewer's repository copy included
them when untracked. The value patterns and the path list now cover these
shapes, with negative tests so prose such as "the Token header" is left alone.

Promotion: promoted - `claude-review-loop` redaction; documented in the three harness SKILL.md files

## 2026-09-23 — Let Claude's own denial settle an out-of-scope reviewer read

Session traces from July to September show about half of all `claude-review-loop`
INVALID results were Opus reaching outside the review root (a Glob on the raw
repository, an absolute `/private/tmp/**` pattern). Claude's `dontAsk` mode had
already refused each of those calls, as a live probe confirmed. The monitor still
killed the review at the tool-use event, so every such run was lost and restarted.
The monitor now holds an out-of-scope call until Claude answers it. A permission
denial is recorded in `denied_tool_uses` and the review continues. Returned data,
any other error, or a verdict before the answer still makes the result INVALID.
The review instruction also names the review root and asks for relative paths.

Promotion: promoted - `claude-review-loop`, harness monitor and review instruction

## 2026-09-23 — Keep fixed round caps out of handoff prompts

"At most three review cycles" appeared in 61 handoff prompts, 32 of them in
September, long after `cross-agent-review-cycle` dropped its cap. The phrase came
from project AGENTS.md files (podcast, pipy) that handoff drafts copied, and
agents that hit the cap stopped for an interactive rescue. Asking for review
cycles until diminishing returns works better in practice. A hard retry limit
in the harness was rejected for the same reason.

Promotion: promoted - `goal-handoff` (both), `handoff-impl`, `implement-handoff`: never copy a fixed cap into a prompt

## 2026-09-19 — Check requirements and generated query plans before adding repair work

Feed-cache staleness was initially treated as a defect without an immediate-removal
requirement. The owner explicitly accepts the existing TTL. Closed the invented
repair backlog item and marked its proposal historical; retained evidence without
presenting the rejected policy as required work.

The selection spike's raw row comparison did not guarantee the ORM emitted an
equivalent index-friendly predicate: SQLite added a boolean equality wrapper,
and inherited Episode IDs were rewritten onto another table. Actual-service
query plans caught both. Switched to a direct comparison Lookup and Post-based
selection, then independently reviewed the delta. A review claim about index
inheritance was disproved with system checks and model introspection, not patched
speculatively. Required findings resolved; advisory-only closure recorded.

Promotion: incident — project plan records the accepted policy and compiler
constraints; existing skills already require evidence-based adjudication.

## 2026-09-19 — Serialize tests that share a SQLite test database

During the feed baseline repair, a focused pytest invocation overlapped the
full check and hit a database lock. A concurrent edit also left that running
suite testing its already-loaded, older fixture version. Discarded that run and
reran the full check only after edits settled, with no competing pytest process.
Review independently closed with required repairs verified and one advisory.

Promotion: incident — existing stable-worktree validation guidance applies;
project checks sharing a test database must run serially.

Reusable agent and process lessons from review cycles, goal handoffs, model
pairing, orchestration, and validation - the things that should change a skill.

## What belongs here

One entry per lesson that would improve a future run in *any* project. If the
lesson only makes sense inside one repository, it belongs in that project's own
workflow log instead.

Not here: raw prompts, transcripts, secrets, large tool output, and per-run
metrics. A line like `Fullcheck10314/135.26s types430 domain100` records what a
run measured, not what the next run should do differently; it is what made the
2026-09 stretch of this log unreadable, and those notes now sit in
`archive/emerge-run-notes-2026-09.md`.

## Every entry carries a promotion status

The point of this log is to change the skills, and the way that stopped
happening was silent: entries accumulated for six weeks while
`cross-agent-review-cycle` and `claude-review-loop` stood still, and by the time
anyone looked, the skills disagreed with each other about when a review loop may
stop. So each entry ends with one of:

- `promoted - <skill>, <section>` - the rule now lives there. That is the goal.
- `pending - <what is missing>` - a real lesson no skill carries yet.
- `incident` - environment or tooling failure with nothing to promote; kept for
  context.

`grep '^- Promotion: pending'` is the backlog.

## Promote or discard, at the end of the cycle

Writing the entry is not the end of the cycle. Before the cycle closes, either
promote the lesson into the skill it affects and mark it `promoted`, or decide
it is not worth a rule and mark it `incident`. `pending` is for a lesson that
needs a change you cannot make right now - not a place to leave everything.

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
- Promotion:
```

## Archives

- `archive/review-cycle-log-2026-05-to-07.md` - closed incident history. Much of
  it describes a review transport that no longer exists.
- `archive/emerge-run-notes-2026-09.md` - per-run project notes that were
  misfiled here. Their reusable content is distilled into entries below.

## 2026-08-12 - Keep Claude Review Directories Outside the Reviewed Repository

- Repo: Daybook public weeknotes repository evidence.
- Implementer: Pi using `openai-codex/gpt-5.6-sol`.
- Reviewer: Claude Opus through `claude-review-loop`.
- Expected: a relative fresh run directory would isolate the review bundle while
  Opus inspected only its harness-owned copy.
- Actual: placing the run directory at `daybook/fresh` made the raw repository
  root a confusing parent of the review root; Opus attempted a Glob against that
  parent and the harness correctly marked the review INVALID.
- Impact: no code was accepted without review, but one review attempt and its
  generated in-repository artifacts had to be discarded.
- Fix or follow-up: create the fresh review directory under `/tmp` (or another
  path outside the repository) and pass that absolute path to `--run-dir`; inspect
  `result.json` and remove any generated worktree artifacts before retrying.
- Status: resolved; the fresh external-directory reviews completed without
  forbidden tool use, and all Critical/Warning findings were closed.
- Promotion: promoted - `cross-agent-review-cycle` creates the run directory with `mktemp -d`, outside the repository

## 2026-09-02 - Honor Reviewer Session Limits Without Relabeling the Gate

- Repos: ops-library, ops-control, and Nyxmon staging reboot hardening.
- Implementer: Codex.
- Reviewers: Claude Opus initially, then Codex `gpt-5.6-sol` at the operator's
  explicit request.
- Expected: complete every round with the default different-family Claude
  reviewer.
- Actual: the operator reported that the Claude session limit was nearly
  exhausted while the Nyxmon review was running and requested GPT-5.6 for the
  remaining reviews. The in-flight Claude review was interrupted and recorded
  as invalid; fresh read-only GPT-5.6 reviews then completed the remaining
  cycles.
- Impact: ops-library and ops-control retained valid initial different-family
  findings, while Nyxmon's completed review evidence is fresh-context but
  same-family and therefore does not satisfy the stricter different-family
  label.
- Fix or follow-up: stop the costly reviewer promptly when the operator signals
  a session constraint, use the explicitly requested reviewer, and state the
  resulting gate distinction rather than silently treating same-family review
  as equivalent. Preserve valid earlier different-family findings and continue
  focused repair verification with the requested model.
- Status: resolved; all Critical and Warning findings were repaired, focused
  GPT-5.6 re-reviews closed cleanly, and the gate distinction was reported.
- Promotion: promoted - `cross-agent-review-cycle` reviewer selection: report a blocked gate, never relabel a same-family review as the different-family one

## 2026-09-02 - Treat Pi Worktree Progress as the Implementer Result

- Repo: Emerge startup hydration time-block compaction.
- Implementer: Pi using `openai-codex/gpt-5.6-sol` under a hard timeout.
- Reviewer: Claude Opus through `claude-review-loop`.
- Expected: Pi would write the implementation, run checks, emit a summary, and
  exit within the supervised window.
- Actual: Pi wrote the planner, tests, and synchronized feature documentation,
  then remained alive with an empty buffered report and no further file
  progress.
- Impact: the implementation existed but its claimed verification and finish
  state were unavailable; treating process liveness as progress would have
  stranded the workflow.
- Fix or follow-up: terminate the exact timed process group after file progress
  stops, inspect the worktree as the source of truth, independently run focused
  and full checks, and send that evidence through the different-family review
  gate.
- Status: resolved; the worktree was validated, two review rounds addressed all
  findings, and no Pi process remained.
- Promotion: promoted - `cross-agent-review-cycle`, Supervising A Noninteractive Implementer

## 2026-09-02 - Re-review When Main Changes The Coupled Endpoint

- Repo: Emerge frontend health polling.
- Implementer: Codex.
- Reviewer: Pi using `openai-codex/gpt-5.6-sol`.
- Expected: a read-only review would verify that both active defaults, tests,
  and documentation moved from five to ten seconds without changing runtime
  behavior beyond cadence.
- Actual: the first Pi review was clean, then `main` advanced with backend
  supervisor-health changes before MR creation. A targeted post-rebase review
  confirmed that `information=basic`, terse lifecycle payloads, overrides,
  backoff, and response handling remained compatible.
- Impact: the coupled upstream delta received meaningful independent scrutiny
  without reopening an unrestricted repository audit.
- Fix or follow-up: after a clean review, re-review only when a rebase changes a
  directly coupled endpoint or assumption; otherwise stop at diminishing
  returns. Keep prompts explicit about duplicated composition defaults and
  statement-neutral coverage-gate failures.
- Status: resolved; both reviews were clean and no reviewer process remained.
- Promotion: promoted - `cross-agent-review-cycle`, Re-review scope containment (a directly coupled path reopens the gate)

## 2026-09-02 - Release Support Claims Need Documentation and Guard-Test Parity

- Repo: django-indieweb 0.6.2 release preparation.
- Implementer: Codex.
- Reviewer: Pi using `openai-codex/gpt-5.6-sol`.
- Expected: version, changelog, CI, dependency, artifact, and SBOM preparation
  would make the Django 6.1 compatibility release ready for final review.
- Actual: the first review found that contributor/development support text
  still stopped at Django 6.0 and that the dependency-floor regression test
  still accepted the vulnerable cryptography 48 floor.
- Impact: release metadata and tests could pass while the documented support
  contract and security-floor guard contradicted the package metadata.
- Fix or follow-up: update all support-matrix documentation together and raise
  the guard-test expectation whenever a security floor is raised; narrowly
  re-review those repairs before closing the gate.
- Status: resolved; both warnings were fixed and the targeted second review
  returned clean with no remaining findings.
- Promotion: promoted - `cross-agent-review-cycle`, Review Prompt Contents: ask the reviewer to verify docs and release notes when behavior changed

## 2026-09-03 - Lifecycle Regressions Should Traverse Production Callbacks

- Repo: Emerge frontend hydration request lifetime fix.
- Implementer: Codex.
- Reviewer: Pi using `openai-codex/gpt-5.6-sol` at the operator's explicit
  request.
- Expected: focused tests around the request-retirement helper would adequately
  guard successful and cancelled targeted hydration attempts.
- Actual: the first review found that the success case invoked the cleanup
  helper directly, so it could pass even if production delivery stopped calling
  that helper.
- Impact: the resource-lifetime fix was correct, but its regression test did
  not initially protect the most important integration seam.
- Fix or follow-up: drive lifecycle regressions through real delivery and
  settlement callbacks, then assert both retained-resource cleanup and the
  associated progress state. Use private helpers only when the helper itself is
  the behavior under test.
- Status: resolved; the repaired success and cancellation tests traverse the
  production callbacks, focused checks pass, and the scoped Pi re-review was
  clean. This same-family review follows the operator's explicit selection and
  is not relabeled as a different-family gate.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Handling Findings: drive an error-boundary regression through the production caller chain

## 2026-09-03 - Treat Reviewer Transport `Not Found` as an Invalid Review

- Repo: Emerge Process timestamp-limit frontend validation.
- Implementer: Codex; reviewer: Pi with `openai-codex/gpt-5.6-sol`.
- Expected: a narrow third round would verify one fractional-step counting
  repair and emit the completion sentinel.
- Actual: two fresh Pi attempts passed the approved-model preflight, then
  `pi -p` returned only `Not Found` with status 1 and no sentinel. Two fresh
  Codex CLI attempts then received HTTP 404 from both the WebSocket endpoint
  and its HTTPS fallback. The initial launch command also had to be rebuilt
  without an unnecessary `rm -f` because the execution safety layer rejected
  that cleanup form.
- Impact: neither `Not Found` attempt counts as a review; the earlier two Pi
  rounds remain valid, but Pi did not verify the last repair.
- Fix or follow-up: stop and clean each invalid session, never infer CLEAN from
  the prompt-echo sentinel or empty/short log, and preserve the frozen
  outstanding finding until a requested reviewer produces a valid verdict.
- Status: externally blocked after bounded fresh retries; implementation and
  focused verification remain available, but no clean review is inferred.
- Promotion: promoted - `cross-agent-review-cycle`: a review without a parseable verdict is invalid, not a pass

## 2026-09-05 - A Pi Report's Self-Reported Identity Is Not Model Evidence

- Repo: Emerge frontend, UCTE Manual replacement filename/path typeahead.
- Implementer: Claude Opus; reviewer: Pi with `openai-codex/gpt-5.6-sol`.
- Expected: the review report would name the reviewing model, so the round
  record could cite the report itself as evidence of the mandatory pairing.
- Actual: the run was healthy — the approved-model preflight passed, the
  sentinel appeared once after about seven minutes, no orphan process survived
  the tmux kill — but the report's own identity section said only "OpenAI
  ChatGPT; exact runtime model/version was not exposed".
- Impact: none to the verdict, but a driver that records the model from the
  report alone would either understate the pairing or overstate what it can
  prove.
- Fix or follow-up: treat the runner as the evidence — the branch rejects every
  model but the approved one, preflights it, and passes it explicitly — and
  record the model from the invocation rather than from the reviewer's prose.
  Ask for the reviewer identity field anyway; a wrong answer there is a signal,
  an absent one is not.
- Status: resolved; round recorded with the model taken from the pinned
  invocation.
- Promotion: promoted - `cross-agent-review-cycle`, Model Roles And Cost: record the model from the invocation, not from the reviewer's prose

## 2026-09-05 - `pgrep -fl 'pi -p'` Does Not Find A Running Pi Reviewer On macOS

- Repo: Emerge frontend, UCTE Manual replacement filename/path typeahead,
  review round 2.
- Expected: the prescribed orphan/liveness check `pgrep -fl 'pi -p'` would match
  the reviewer process while it ran, and an empty result would mean the reviewer
  had not started or had already exited.
- Actual: the reviewer was running normally, but the pattern matched nothing.
  On this host the process argument list is rendered as the bare command name
  followed by the inherited environment, so the flags the pattern looks for are
  not in the searched text at all. A driver polling for CPU activity with that
  pattern would have declared a healthy run dead at the first check and retried
  a review that was already in flight.
- Impact: a false "no reviewer running" signal, in the exact spot where the
  procedure tells a driver to kill orphans and retry - i.e. it can burn a review
  cycle and, worse, mask a genuine orphan later because the same check also
  returns empty when one exists.
- Fix or follow-up: verify liveness by the wrapper instead of the flags. The
  runner script's own path is unique per run and does appear in the argument
  list, so match on that, or walk down from it to its child. Keep the tmux
  session check as the primary liveness signal, since it is the thing that
  actually ends when the run ends, and use the process check only to confirm
  nothing survived the kill.
- Status: resolved for this round - liveness was confirmed from the process
  tree and the tmux session, and the post-kill orphan check was repeated with a
  pattern that matches the wrapper.
- Promotion: pending - the orphan check is in the skill, but not that `pgrep -fl 'pi -p'` cannot see the reviewer on macOS; match the wrapper path instead

## 2026-09-06 - A Converging Plan Review Can Be Closed Into The Code Review

- Repo: nyxmon, site connectivity detection (plan + implementation + code
  review), reviewer GPT-6 Astra via `codex exec` read-only, implementers
  Claude Opus 5 subagents, orchestrator Claude Fable 5.1.
- Expected: the plan review would reach CLEAN within a few rounds.
- Actual: findings went 15 → 7 → 3 → 1 → 1 → 1 → 1; the last four rounds
  each narrowed the same recheck-completion argument to a smaller corner
  (time bound → exact fence → read ordering → exhaustion path → transaction
  placement), with the reviewer itself noting the last two would be Warnings
  without the plan's own stated bound.
- Impact: four rounds of roughly ten minutes each for one paragraph of the
  design; a fixed "must be CLEAN" rule would have added more.
- Fix or follow-up: stop when successive rounds only narrow one argument and
  the final repair is mechanical; carry it as a mandatory verification item
  into the code review, which can check the real transaction placement
  instead of prose. The code review then confirmed it in round 1 and found
  eight unrelated Criticals that no plan round could have seen.
- Status: resolved; recorded in the project's `docs/workflow/` record.
- Promotion: promoted - `claude-review-loop` step 4 stops a loop whose rounds only narrow one argument, and `--slice-id` now computes that signal

## 2026-09-06 - `pre-commit run --all-files` Skips Untracked Files

- Repo: nyxmon, same cycle.
- Expected: `uvx pre-commit run --all-files` covers every file an implementer
  created.
- Actual: it only inspects git-tracked files, so nine new Python modules and
  tests were never linted by that command; a subagent noticed and ran ruff
  directly, the orchestrator then added `pre-commit run --files <untracked>`
  to every validation pass.
- Impact: a "lint clean" claim on new files was unproven until the explicit
  run; no actual lint defect surfaced.
- Fix or follow-up: always run the hooks with `--files` over
  `git ls-files --others --exclude-standard` when the slice adds files.
- Status: resolved.
- Promotion: promoted 2026-09-10 - `commit-workflow`, step 5

## 2026-09-07 - Baseline consultation snapshots need a Git HEAD

- Repo: django-cast editor API rich-text security fix.
- Expected: a temporary Git repository containing selected baseline source as
  untracked files would be immediately reviewable by claude-review-loop.
- Actual: bundle collection uses HEAD for diffstat and rejected the empty repo
  before any reviewer was spawned.
- Impact: one invalid preflight; no review verdict was consumed.
- Fix: create an empty initial commit in the temporary snapshot only, then
  invoke the harness with a fresh run directory. Keep source evidence below
  the repository-derived boundary and intent in the trusted context file.
- Status: resolved; direct Opus 5 consultation completed successfully.
- Promotion: promoted - harness behavior: bundle collection needs a HEAD and refuses an empty repository before spawning a reviewer

## 2026-09-07 - Review exception handling through the caller chain

- Repo: django-cast editor API rich-text sanitization.
- Expected: moving configuration resolution outside a helper's invalid-input
  guard would keep configuration failures visible as server failures.
- Actual: an outer custom-block conversion envelope still caught TypeError
  and downgraded it to a 400. A helper-only regression missed that interaction.
- Impact: operational failures could look like invalid author input.
- Fix: preserve the cause in ImproperlyConfigured and test the caller path
  as well as the helper.
- Review outcome: direct Claude Opus 5 consultation, then three implementation
  reviews; warnings declined from four to one to zero. The last verdict was
  Suggestion-only and accepted as advisory at diminishing returns, not CLEAN.
  Optional preservation and nested-error UX improvements were tracked as
  follow-ups; required checks and coverage passed.
- Status: resolved; use call-chain regressions for error-boundary changes.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Handling Findings

### Django-cast dependency re-review attempted an out-of-scope glob

- Expected: the supervised Opus 5 re-review would inspect only the harness-owned
  bundle and return a structured verdict for the dependency-security repair.
- Actual: Claude requested a Glob target at the parent of its canonical review
  directory. The harness rejected the attempt and returned INVALID with no
  usable findings.
- Impact: the repair remained unverified; no clean result was claimed.
- Fix: discard the invalid run and retry from a fresh directory with concise,
  self-contained caller context that does not invite inspection of prior logs.
- Follow-up: three nested-directory retries repeated the out-of-scope Glob and
  were discarded. A generic temporary review directory restored valid reviews.
- Status: the final valid Opus 5 review reported zero Critical/Warning findings
  and three Suggestions. Two low-cost documentation/tool-pinning suggestions
  were applied. A metadata/list synchronization helper was declined because a
  full lowest-direct resolution selected unrelated, Python-incompatible legacy
  packages; broad dependency-baseline work is separate from the audited floors.
- Promotion: promoted - `claude-review-loop`: an inspection target outside the run directory makes the result INVALID; retry from a fresh generic directory

## 2026-09-07 — Traefik transaction review scope

Expected: focused repair reviews stop after material findings close. Observed:
reviewer repeatedly parsed a slash-containing Git branch as a repository path and
raised documentation warnings despite the tracked path existing. Impact: avoidable
wording churn. Resolution: verify refs/paths with Git and reject the false finding
with evidence; also execute the claimed check-mode failure before accepting it.
Status: loop stopped after three passes; no unconditional CLEAN claim.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Handling Findings: disprove a false finding with evidence rather than editing around it

### 2026-09-08 — Traefik prerequisite review

A focused Claude Opus 5 preparation review added enforced shared-middleware
preservation and explicit invalid-target refusal. The second review incorrectly
inferred a host-guard bypass from an incremental diff; the unchanged target
pre-task plus an actual limited-host refusal disproved it. Three rounds ended
with diagnostic-wording Suggestions only, accepted as advisory at diminishing
returns. Real systemd failure-path tests and live no-change refusals supported
the disposition. Keep unchanged guard context visible when reviewing small repair
deltas; do not reopen a broad audit for wording-only feedback. No delegated
subagents were used.
- Promotion: promoted 2026-09-10 - `claude-review-loop`: a delta round needs the unchanged guard context in `--context-file`

### 2026-09-08 — Finish proxy updates without unnecessary console gates

The owner rejected an overbuilt rescue-console prerequisite for a proxy-only
patch. Replaced it with truthful verified SSH recovery evidence while preserving
checksums, backups, exact file scope, paired records and automatic rollback. All
three live Ansible updates succeeded. Added a reusable Ansible health-probe task
so inspection setup is reproducible too. Three focused Claude Opus 5 reviews
improved transport, timeout/empty-baseline handling, interpreter consistency and
cleanup tests. The final claim that the interpreter diagnostic misstates a missing
binary was rejected: the text explicitly names the required absolute path and
minimum version, without asserting which condition failed. Remaining suggestions
were diagnostic/test-output wording; stopped at diminishing returns. This was an
adjudicated review closure, not an unconditional CLEAN verdict. Do not let a plan
invented by the agent become a user-authorization barrier for a routine patch.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Handling Findings: an agent-invented prerequisite is not a user-authorization barrier

### 2026-09-08 — django-cast security repair review, first round

Expected: the full implementation and planning record reach review in sync.
Observed: Opus 5 reported one backlog-sync Warning and three Suggestions;
implementation checks passed but the backlog still described fixed findings as
future work. Narrowed the backlog to deferred hardening, added an allowed/denied
admin-search regression, and made endpoint test assertions use route names.
Verified the separate author self-edit access policy and tracked it without
expanding the creation/preview repair. The search test found no production defect.
Status: accepted repair delta awaits focused re-review; no clean claim yet.
Lesson: update active backlog items as soon as implementation validation passes,
then keep subsequent reviews tied to accepted findings and the repair delta.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Handling Findings: sync the backlog as soon as validation passes

### 2026-09-08 — django-cast security repair review closure

The focused second claude-opus-5 review resolved the backlog Warning and
returned only two Suggestions. Added a permitted nonmatching search result so
the regression distinguishes searched from unsearched paths, and completed
the chronological post-repair evidence. No production code changed after round
one. Stopped advisory at diminishing returns: no Critical/Warning remains, and
another model pass would mostly revisit a small test assertion and bookkeeping.
The author self-edit/delete access policy remains an explicit separate follow-up.
Both reviews were direct and had no skipped/truncated/redacted evidence or
forbidden tool use. Final validation follows the tiny test refinement; no commit.
Lesson: security search tests need both permission controls and query selectivity
controls; avoid waiting for review to point out missing contemporaneous evidence.

Final django-cast gate after the search-test control: just check passed,
2,616 passed / one PostgreSQL-only skip / 100% Python coverage; Ruff and mypy
passed. Changes remain uncommitted.
- Promotion: pending - the specific lesson (a security test needs both a permission control and a selectivity control) is not in any skill

### 2026-09-08 — frontend refactoring plan: qualify reviewer-proposed invariants

Two requested direct claude-opus-5 xhigh cycles completed. First-round acceptance
repairs were useful, but adopted cardinality and epoch-accounting wording
overgeneralized source behavior; the second round narrowed those statements.
Trace the entire admission/retirement path before promoting a reviewer
suggestion into a plan invariant: global keys can bypass a scoped counter,
and shutdown can intentionally bypass ordinary outcome recording. Final
factual corrections passed local source/probe/build/link checks. Stopped at
the user's requested two cycles; the final Warning repair is not independently
re-reviewed, so no CLEAN or commit-readiness claim. No source changes or commits.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Handling Findings: qualify a reviewer-proposed invariant before adopting it

## 2026-09-09 - One Review Loop, Three Contradictory Stopping Rules

- Repo: agent-stuff skills.
- Expected: the review loop stops on the value-driven rule recorded in
  `cross-agent-review-cycle` on 2026-07-30.
- Actual: three files disagreed, and which one applied depended on what the
  session happened to load. `claude/skills/cross-agent-review-cycle` was a
  pre-2026-07-30 duplicate with a hard three-cycle cap; `claude-review-loop`
  said the opposite - "do not impose a default or absolute round cap ... round
  count alone is never a stopping reason"; `pi-review-loop` said "only proceeds
  when Pi returns CLEAN" plus a fixed three-round cap. Worse, `~/.claude/skills`
  had no `cross-agent-review-cycle` symlink at all, so outside the emerge
  workspace a Claude session drove the harness with none of the containment
  rules.
- Impact: whole-slice re-review rounds that never converge on large diffs. The
  September entries above show the pattern: every closure was adjudicated by
  hand as "advisory, NOT CLEAN, stop at diminishing returns", because no skill
  said the loop may end there.
- Fix: deleted the drifted Claude copy and symlinked the single agent-neutral
  copy under `codex/skills/` for every agent; made `claude-review-loop` and
  `pi-review-loop` defer to it instead of restating the rules; made a
  Suggestion-only verdict terminal by default; added mechanical stop conditions
  (two rounds without a Critical/Warning decrease; successive rounds narrowing
  the same argument, which the 2026-09-06 nyxmon 15-7-3-1-1-1-1 curve shows).
- Follow-up: `claude-review-loop` now takes `--record-baseline` (snapshot the
  reviewed content as a dangling commit) and `--baseline-ref` (bundle only what
  changed since it), so a re-review round is scoped in the bundle instead of
  being asked for in the prompt. Still open: the same option in the Pi harness,
  whose bundle is an older and much smaller implementation, and a cross-round
  ledger that computes the convergence signal instead of leaving it to the
  driver's judgment.
- Status: resolved for the rule drift; promoted into the skills, not just logged.
- Promotion: promoted - this entry records the skill change itself

## 2026-09-09 - Model Choice And Reasoning Effort Are Separate Axes

- Repo: agent-stuff skills.
- Expected: asking the review harness for a stronger model changes one thing.
- Actual: effort was inferred from the model name - `xhigh` if the id contained
  "opus", `high` otherwise - so `--model fable` silently reviewed at lower
  effort than the default `opus`, and no table said what any other model should
  get. The inference also outlived its reason: `xhigh` was what the Opus 4.x
  generation needed.
- Impact: an unstated policy that moved two variables in opposite directions,
  and no guidance at all for the newer models now in use.
- Fix: effort now follows the model generation, not the price or the name -
  `high` for Opus 5, Fable, Sonnet, GPT-5.6 and anything unrecognized, `medium`
  for the Astra generation, `xhigh` only for Opus 4.x. Added a role/model table
  to `cross-agent-review-cycle`: mid tier by default everywhere, top tier
  (Fable, Astra) opt-in per run and recorded, and a cheaper reviewer allowed for
  delta re-review rounds - but only rounds actually scoped with
  `--baseline-ref`, and never for verifying a Critical repair.
- Status: resolved. The cheaper-delta-reviewer tier is a deliberate experiment;
  record which tier each round used, from the invocation rather than from the
  reviewer's own report, so it can be evaluated later.
- Promotion: promoted - this entry records the skill change itself

## 2026-09-10 - The Stop Conditions Needed Somewhere To Live

- Repo: agent-stuff, `claude-review-loop`.
- Expected: the mechanical stop conditions added on 2026-09-09 - a required
  finding surviving two repairs, a Critical/Warning count that stops falling -
  would end loops that judgment alone had been ending by hand.
- Actual: both conditions are questions about the rounds *together*, and nothing
  held the earlier rounds. A driver has to carry round N-1's counts in context;
  after a compaction, a fresh session, or a handoff it no longer can, which is
  exactly the state in which an agent runs one more round.
- Impact: the rules were only as good as the driver's memory of the loop it was
  in - so on the long, expensive slices they were least likely to apply.
- Fix: `--slice-id` appends one summary-safe line per completed round to
  `~/.cache/review-loop/ledger/<slice>.jsonl` - severity counts, finding
  fingerprints, model, effort, duration, baseline; no finding text, no
  repository content. The harness reads the slice back, reports
  `LOOP: <status> - <reason>`, records `convergence` in `result.json`, and exits
  `4` when the loop is not converging, so a driver that only knows `0`/`1`
  cannot mistake it for ordinary findings. Fingerprints ignore digits, so a
  finding that only moved line numbers still counts as the same complaint.
  Failed rounds are not recorded: they reviewed nothing.
- Status: resolved. Exit `4` ends the loop; it is not a verdict that findings
  are resolved, and the commit gate is unchanged.
- Promotion: promoted - this entry records the harness change itself

## 2026-09-10 - Freeze Worker Edits Before Collecting A Full Check

- Repo: emerge frontend, distilled from the 2026-09-08 run notes now in
  `archive/emerge-run-notes-2026-09.md`.
- Implementers: three GPT-5.6 Sol workers under one coordinator.
- Expected: a full check collected while workers finish their last edits would
  reflect the code being reviewed.
- Actual: concurrent test edits landed during collection, and the run produced
  stale assertions - a result that described neither the old code nor the new.
- Impact: a green or red full check that proves nothing, discovered only when
  the numbers did not match the worktree.
- Fix or follow-up: stop every worker and let its edits settle before starting
  the check that will be quoted as evidence. A check is evidence only of the
  tree it actually ran against.
- Status: resolved.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Supervising A
  Noninteractive Implementer

## 2026-09-10 - Verify A Worker's Claimed Change Against The Code

- Repo: emerge frontend, distilled from the 2026-09-08 run notes.
- Expected: a worker reporting that it made a parameter required had made it
  required.
- Actual: the saved signature still had it optional; the claim survived until a
  final correction pass compared the report against the source.
- Impact: a coordinator that trusts worker reports carries a false statement
  into the review prompt, where it costs a round to discover.
- Fix or follow-up: check the claimed edit in the code before quoting it as
  done. This is the same rule as reading the worktree rather than the report
  when an implementer hangs, and as taking the reviewer's model from the
  invocation rather than its prose.
- Status: resolved.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Supervising A
  Noninteractive Implementer

## 2026-09-10 - A Coordinator Pass Catches Test Weakening A Reviewer Never Sees

- Repo: emerge frontend, distilled from the 2026-09-08 run notes.
- Expected: the review gate would catch a weakened assertion.
- Actual: a worker replaced a whole-map emptiness check with a single-key
  absence check - strictly weaker, and invisible in a diff that looks like a
  reasonable refactor. The coordinator caught it before the review and asked for
  count-preserving queries instead.
- Impact: none, because it was caught early; a reviewer reading only the diff
  would likely have passed it.
- Fix or follow-up: when a worker edits tests, compare what each assertion can
  still detect, not whether the test still passes. Reviewers are good at new
  code and blind to a guard that quietly got smaller.
- Status: resolved.
- Promotion: pending - no skill says to diff assertion strength when a worker
  touches tests

## 2026-09-10 - A Test That Also Passes Against The Old Code Is Not A Reproduction

- Repo: emerge frontend, distilled from the 2026-09-07 run notes.
- Expected: a regression test accompanying a repair demonstrates the defect.
- Actual: the test passed against the pre-repair code as well. It documented
  behavior that was already true rather than reproducing the fault - and a
  rollback test returning False passed before its injected failure ever ran.
- Impact: a repair looks verified when nothing proved the defect existed or that
  the fix is what removes it.
- Fix or follow-up: run a new regression against the old code and require it to
  fail. If it passes, it is behavioral-preservation evidence - useful, but not a
  reproduction, and it should not be offered to a reviewer as one. Assert that
  the injected fault actually executed.
- Status: resolved.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Handling Findings

## 2026-09-10 - Rename The Innocent Local Instead Of Weakening Redaction

- Repo: emerge frontend and django-cast, distilled from the 2026-09-07 run notes.
- Expected: the bundle's secret redaction would leave ordinary code alone.
- Actual: two local variables named `token` in issuance code were redacted as
  possible credentials, and a diagnostic key was flagged the same way. The
  reviewer saw holes in unchanged code.
- Impact: a scoped result and a distracted reviewer, with a standing temptation
  to loosen the pattern that produced the false positive.
- Fix or follow-up: rename the local to what it actually holds. A redaction
  false positive is cheap; a credential that reaches a model because the pattern
  was relaxed is not. Check `redactions` in `result.json` and confirm each one
  is genuinely innocent rather than assuming it.
- Status: resolved.
- Promotion: promoted 2026-09-10 - `claude-review-loop`, redaction notes

## 2026-09-10 - A Log Nobody Promotes Is Write-Only

- Repo: agent-stuff.
- Expected: lessons recorded here would reach the skills.
- Actual: the last five commits before this pass were log-only, 480 lines added
  while the skills stood still since 2026-07-30 - and an earlier commit,
  `aa524fc`, had already been a catch-up promotion pass, so this was the second
  time. Entries had also degraded into per-run metric dumps that no later
  session could mine, and emerge execution notes were being written into a log
  reserved for cross-project lessons.
- Impact: the drift that let one review loop carry three contradictory stopping
  rules. Nothing warned anyone, because an unpromoted entry looked exactly like
  a promoted one.
- Fix or follow-up: every entry now ends with a `Promotion:` line, and promoting
  is part of closing the cycle rather than a later pass;
  `grep '^- Promotion: pending'` is the backlog. Pre-2026-08 history and the
  misfiled project run notes moved to `archive/`, cutting the active log from
  3,298 lines to a readable one. Ten lessons that had been sitting unpromoted
  went into `cross-agent-review-cycle`, `claude-review-loop`, and
  `commit-workflow` as part of this pass.
- Status: resolved.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Learning Logs;
  and this file's own header

## 2026-09-10 - The Pi Bundle Had Fallen Behind On Redaction, Not Just Features

- Repo: agent-stuff, `pi-review-loop`.
- Expected: porting `--baseline-ref` to the Pi harness would be a feature port.
- Actual: `pi_review_loop/bundle.py` was a copy of an older `claude-review-loop`
  bundle and had missed everything added since: no secret redaction at all, no
  `--no-ext-diff`/`--no-textconv` guard against repository-configured diff
  drivers, no symlink or non-regular-file checks before opening an untracked
  path, and text-mode git output instead of byte-exact decoding.
- Impact: Pi runs with `--no-tools`, so the bundle is the whole review surface -
  and it went to an external provider unredacted. A secret-looking untracked
  file was sent verbatim. Nothing indicated the copy had fallen behind, because
  the older code still worked.
- Fix or follow-up: `pi_review_loop.bundle` and `pi_review_loop.ledger` now
  delegate to the shared modules by relative path and fail loudly at import
  rather than falling back to a local copy, so both gates share redaction,
  scoping, the delta bundle, and one slice history. Two gaps the merge closed in
  the other direction: the Claude harness had no empty-worktree guard, which Pi
  had, and Pi's `scoped_clean` did not account for redactions, which it now has
  to.
- Status: resolved; verified end to end on a scratch repository, including a
  `.env` that no longer reaches the bundle and a slice whose rounds ran on both
  harnesses appearing as one history.
- Promotion: promoted 2026-09-10 - the fix is the shared module itself;
  `pi-review-loop` SKILL.md now states the dependency and the redaction contract

## 2026-09-10 - A Fixed Completion Sentinel Fails When The Reviewed Repo Documents It

- Repo: agent-stuff, reviewing the review skills with `codex exec`.
- Expected: polling for two `=== REVIEW COMPLETE ===` matches ends on the report,
  since `codex exec` echoes the prompt exactly once.
- Actual: the poll returned mid-review with three matches. The repository under
  review documents its own output contract, so the reviewer's file reads echoed
  the sentinel into the log. Re-arming on `[review pipeline statuses:` failed the
  same way - the runner script is quoted in the skill too. The reviewer was still
  working both times.
- Impact: a driver that trusted either signal would have reported a partial log
  as the verdict, or killed a live reviewer.
- Fix or follow-up: use a per-run nonce (`openssl rand -hex 8`) in the sentinel
  and poll for that; nothing already in the repository can contain it. Waiting on
  the reviewer process is the fallback when the runner holds the pane open. Any
  fixed marker is only safe while the reviewed material cannot quote it - which
  is exactly what a repo of review skills does.
- Status: resolved; the third attempt waited on the process and captured the
  full report.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, reviewer procedure
  step 4

## 2026-09-10 - GPT-5.6 Review Of The Review-Loop Changes

- Repo: agent-stuff, commits `0112b1c..9d1793e`.
- Implementer: Claude Opus 5. Reviewer: Codex `gpt-5.6-sol` at high reasoning,
  read-only, model taken from the invocation rather than the report, which named
  only "GPT-5".
- Expected: a first review of six commits that had passed 349 stub-driven tests.
- Actual: 4 Critical, 7 Warning. The gate-relevant one: `--staged-only`
  `--record-baseline` snapshotted worktree content the reviewer never saw, so a
  later delta would treat unreviewed lines as reviewed. Reproduced directly
  before accepting it.
- Impact: the delta feature could have passed content nobody reviewed - the exact
  failure it was built to prevent. Found on code that a full test suite called
  green, because every end-to-end check used stub reviewers.
- Fix or follow-up: staged-only baselines now snapshot the index; blobs are
  written with `hash-object` so no configured clean filter runs from the
  snapshot, and untracked files enter as the redacted bytes that were actually
  sent; a path that is both staged-deleted and untracked is recorded absent and
  re-sent in full every round; the private index has a unique name so it cannot
  delete a caller's file; ledger append and read share one lock; `read_rounds`
  survives malformed counts and undecodable bytes; the default slice id keys on
  the commit rather than the branch. One Critical was qualified rather than
  accepted: clean filters do run, but from `git diff` during collection - as they
  would for any local `git diff` - not from the snapshot path, which no longer
  calls `git add`. The documentation now says so.
- Status: repaired; awaiting a delta re-review of the repair.
- Promotion: incident - the durable rule (a stub-verified harness is unverified)
  is already carried by the run-notes lesson on reproduction evidence

## 2026-09-10 - Round 2: Every Critical Was Caused By The Round-1 Repair

- Repo: agent-stuff, repair delta `9d1793e..b92f511`.
- Implementer: Claude Opus 5. Reviewer: Codex `gpt-5.6-sol` at high, read-only.
- Expected: a bounded delta re-review confirming eleven repairs.
- Actual: 4 Critical, 0 Warning, 0 Suggestion - all four introduced by the
  repair, each with a reproduction the reviewer ran itself. Ambiguity detection
  compared tracked changes against the *accepted* untracked files, so a refused
  secret-looking path was missed and `git rm --cached .env` wrote the raw
  credential into the baseline. The new worktree encoder treated every
  non-regular, non-symlink path as deleted, so a submodule vanished from the
  baseline and a later advance reported no changes. `_staged_tree` copied
  `$GIT_DIR/index` while collection honors an inherited `GIT_INDEX_FILE`. And
  the skill's copyable poll command still grepped the fixed sentinel that the
  prose two paragraphs above had just declared unsafe.
- Impact: the round-1 repair for a secret-exposure warning introduced a
  secret-exposure Critical, and the fix for one silent-omission bug introduced
  another. A repair delta is not a safer diff than the original.
- Fix or follow-up: ambiguity is judged against every untracked path including
  refused ones; a path that exists but cannot be encoded is left at its HEAD
  state and reported, never recorded as deleted, and submodules are encoded as
  `160000` gitlinks; `_staged_tree` honors `GIT_INDEX_FILE`; the poll snippet
  builds on the nonce. All three code findings were reproduced against the
  reviewer's own scenarios before and after the fix.
- Status: repaired; a third bounded re-review of this delta follows.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Judging the
  evidence a repair offers: review the repair delta as its own change, since a
  repair is where the last review's blind spot lives

## 2026-09-10 - Three Rounds In, The Defects Were All In One Hand-Rolled Encoder

- Repo: agent-stuff, `claude-review-loop` baseline snapshot.
- Reviewer: Codex `gpt-5.6-sol` at high, three bounded rounds.
- Trajectory: 11 findings (4 Critical, 7 Warning), then 4 (all Critical), then 4
  (3 Critical, 1 Warning). Required-finding count 11 -> 4 -> 4: falling, then
  flat. Every Critical after round 1 was introduced by the previous round's
  repair, and every one of them landed in the same place - the code that builds
  a git tree from worktree state by hand.
- What that code kept getting wrong: submodules encoded as deletions, then a
  superproject HEAD encoded as a false gitlink; unreadable paths encoded as
  deletions; an alternate index read from the wrong place, then read relatively
  against the wrong directory; secret-looking paths excluded from an ambiguity
  test that decided whether a credential entered the baseline.
- Impact: three review rounds and roughly 330k reviewer tokens, most of it spent
  rediscovering that git object semantics have more cases than an encoder
  written in an afternoon models.
- Fix or follow-up: `git add` into the private index handles every one of these
  cases because git owns them. It was replaced in round 1 for two reasons -
  configured clean filters run, and raw bytes enter local blobs - and both have
  since been measured as weaker than they looked: filters already run during
  ordinary diff collection, and the blob is a local dangling object holding
  content that is already in the worktree. Reverting the encoder to `git add`
  and documenting the two caveats removes the whole defect class.
- Status: repairs for all three rounds are committed and green; the design
  question is open and belongs to the operator, not to another review round.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Judging the
  evidence a repair offers: when successive rounds keep finding new defects in
  one component rather than narrowing, the design is the finding

## 2026-09-10 - Cheap Implementer, Expensive Reviewer, Delta Rounds: It Converged

- Repo: agent-stuff, replacing the hand-rolled snapshot encoder with `git add`.
- Implementer: Codex `gpt-5.6-sol` at high, driven noninteractively under a 2400s
  cap. Reviewer: fresh-context Claude Opus 5 through `claude-review-loop`, one
  round per repair, each scoped with `--baseline-ref` and recorded under one
  `--slice-id`.
- Expected: after three rounds where the driver both implemented and repaired,
  splitting the roles would at least not be worse.
- Actual: 3 Warnings, then 1 Critical + 1 Warning, then 2 Suggestions and the
  ledger's own `converged` verdict - the first time that signal fired on real
  work rather than stubs. The implementer also ran each new regression test
  against the unfixed code first and reported the failures, so the tests are
  reproductions rather than preservation evidence.
- Impact: the same component that produced seven Criticals in three
  self-implemented rounds converged in three delegated ones, and the two
  reviewers disagreed usefully rather than agreeing: GPT-5.6 found the encoder's
  git-object gaps, Opus found that `:(literal)` does not restrict a pathspec to
  one entry and that `git ls-files` is cwd-scoped while `status --porcelain` is
  root-relative.
- Fix or follow-up: keep the split for work of this shape - the reviewer being a
  different family from the implementer matters more than either being the
  strongest available model, and every finding still has to be reproduced by the
  driver before it is accepted or rejected. Two findings were rejected this way:
  a claim that `import stat` had become dead, and an alternate-index write that
  traced to collection's own `git diff` rather than to the repair.
- Status: converged; both Suggestions applied afterwards as diagnostics-only
  changes without another agreement pass. Uncommitted, awaiting the operator.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Model Roles And
  Cost already carries the role split; this entry is its first real evidence

## 2026-09-10 - Reviewing the plan before the code paid for itself; heredoc backticks bit again

- Expected: a small Qt sizing bugfix would need one or two code-review rounds.
- Actual: four plan rounds (11 Warnings -> 5 -> 3 -> ready) then three code
  rounds (2 Warnings -> 1 -> clean). The plan rounds were where the value was:
  three of round 1's findings corrected outright factual errors in my written
  diagnosis - the wrong commit blamed for the regression, a risk-table claim
  about tests that already set their own minimum, and a claim that existing
  tests covered a shortcut they call directly. Had those gone into the
  implementation they would have been repaired as code instead of as prose.
- Impact: the implementation needed no rework of its shape. Both code-round
  Warnings were in the periphery (a dev tool sharing the sizing knob, and a
  touchpad gesture), not in the fix itself.
- Fix or follow-up: for a change whose difficulty is arithmetic and environment
  facts rather than structure, review the plan first and put every constant in
  it with the measurement that produced it. Two of the reviewer's own
  recommendations were then disprovable by measurement - a layout size
  constraint it wanted unconditionally turned out to change nothing, and a
  "treat zero frame margins as undecorated" rule was wrong because the offscreen
  platform reports QMargins(2,2,2,2). Measuring beat arguing in both directions.
- Second lesson, a repeat: I built a review prompt with an unquoted heredoc
  whose body contained a backticked identifier, and the shell executed it as a
  command substitution, silently corrupting the prompt and launching a review
  against it. The skill already warns about this for code fences; the body only
  needs one backtick, and an identifier in backticks is the likelier form in a
  review prompt. Killed the run and relaunched from a quoted heredoc.
- Status: converged clean; uncommitted, awaiting the operator.
- Promotion: promoted 2026-09-10 - `cross-agent-review-cycle`, Wrapper Shell
  Hazards, to say the quoted delimiter is required whenever the body contains a
  backtick at all, not only a code fence.

## 2026-09-19 - Isolated dependency-adoption review recovered after invalid inspection

- Expected: a direct Claude Opus 5 review confined to the harness bundle.
- Actual: the first attempt tried a parent-directory Glob; the harness rejected
  it as INVALID. A fresh isolated attempt completed with suggestions only.
- Impact: the invalid attempt supplied no review evidence; no permissions or
  sandbox settings were relaxed.
- Resolution: retry in a fresh run directory, strengthen the low-cost test
  assertion, and reject the dependency-declaration suggestion with evidence
  from the unchanged project manifest. No further agreement-seeking round.
- Status: resolved; the reviewed implementation remains uncommitted.
- Promotion: incident - existing isolation, retry and suggestion-only stopping
  rules cover this case; no skill change is needed.


## 2026-09-19 - Pi review routing and local-state permissions

- Expected: use the existing Pi harness and diagnose model preflight failures accurately.
- Actual: cross-agent-review-cycle still prescribed a separate tmux runner; denied authentication/settings locks were reported as generic model unavailability.
- Impact: no review started; repeated attempts and login advice would not repair local permissions.
- Fix: route Pi to pi-review-loop, honor explicit user reviewer selection, and distinguish state-lock denial from missing authentication before accepting partial model listings.
- Status: installed after the user enabled full access; regression checks cover both model-resolution entry points. Pi with openai-codex/gpt-5.6-sol independently returned CLEAN without omitted, truncated or redacted evidence. Existing log edits preserved.
- Promotion: promoted - cross-agent-review-cycle, Reviewer Procedure; pi-review-loop, failure interpretation and model preflight.

## 2026-09-20 - Preserve native failure semantics in Ansible diagnostics

- Expected: sanitize management-command errors without allowing deployment to continue.
- Actual: suppressing native failure handling and rebuilding it from return codes missed negative exits and module failures with a zero process exit. Successive scoped reviews exposed the incomplete replacement.
- Resolution: use native Ansible block/rescue semantics and abort with bounded categories; exercise real command, signal and module failures through the included production helper, checking that downstream work is never reached.
- Review preparation incident: repository source was copied into trusted review context after compaction. The final attempt was cancelled and restarted with caller-authored invariants only; source remains behind the harness evidence boundary.
- Status: corrections implemented and locally verified; independent delta review recorded in the Daybook implementation report. No production activation.
- Promotion: incident - existing native-mechanism, executable-evidence and trusted-context rules already cover both failures; no additional skill rule is needed.

## 2026-09-21 - Diagnose ownership failures before changing production guards

- Expected: SSH fixture race tests reach their injected boundary.
- Actual: macOS inherited the temporary parent's wheel group while fixtures expected the contributor's primary group, so ownership checks rejected setup before the race.
- Resolution: set the private fixture root's group before creating children; avoid chown when already correct. Production guards and test assertions remain unchanged. Independent Opus/high review reported suggestions only; alternate effective-group wrappers are outside the documented normal-user test environment.
- Status: targeted suite and hooks pass; complete infrastructure validation is tracked in the Daybook evidence report.
- Promotion: incident - project-specific fixture behavior is documented in ops-library TESTING.md; existing evidence-first review rules need no extension.

## 2026-09-21 — Operations rollout integration checks

Expected the reviewed disabled-first playbooks and restore helper to work under
their actual remote identities. Live staging caught an off-by-one shared-secret
path, macOS sudo inheriting an inaccessible root working directory, and a
service restore helper lacking directory write access for atomic replacement.
All stopped before unintended admission; legacy imports were restored with
marker/ledger/plist integrity checks. Corrected the concrete deployment contracts
and proved backup/replay recovery in an isolated database. Keep real privilege
and path checks in attended deployment evidence; unit contracts alone do not
prove environment integration.

Promotion: incident — existing live-deploy and documentation requirements cover
these failures; project regressions and runbook evidence carry the fixes.

## 2026-09-21 — Operations backup monitoring repair

Expected several notification-suppression predicates to form a conjunction. Source inspection before deployment showed Nyxmon evaluates them as alternatives, which would have hidden schedule-contract failures. Split freshness grace and unsuppressed schedule checks, then exercised the persisted configuration through the installed suppression implementation with drift, pause and overdue scenarios. The bounded Opus review cycle closed with advisory findings only; no reviewer delegation was used. Status: fixed and verified.

Promotion: incident — project-specific predicate semantics; the existing requirement to verify repairs through their production caller already covers the lesson.

## 2026-09-21 — Acceptance documentation versus review-only evidence

A documentation closure review treated a temporary evidence patch as a shipped repository artifact despite its stated scope, and confused absence of an active operation with absence of a persisted operation row. Compared both claims with the exact staged files and measured database state, rejected them, and stopped the cycle after applying the actual documentation fixes. Also retained the separate capacity-policy follow-up instead of treating functional acceptance as approval of that policy. Status: adjudicated and closed.

Promotion: incident — existing guidance to reproduce claims and stop on disproven findings already covers this case.

## 2026-09-21 — Content rollout noindex assertion

A temporary acceptance script incorrectly required an HTTP noindex header although the application deliberately emits a robots meta tag. The guarded transaction rolled back all target revisions; an independent snapshot confirmed unchanged content. Corrected the assertion to inspect the configured meta tag, reran the import and retained browser verification. Status: corrected; production implementation was unaffected.

Promotion: incident — inspect the configured contract before copying rollout assertions; existing evidence-first validation guidance already covers this case.

## 2026-09-21 — Planning review and unchanged recovery identities

A scoped planning review improved category mapping and cross-binding fault isolation, then narrowed repeatedly around diagnostic marker lifecycle. Its last warning assumed an in-place attempt reset that the actual recovery protocol cannot perform. Checked every current-attempt assignment and the explicit supersession path, ran the real PostgreSQL recovery suite, documented the unchanged identity invariant, and stopped the plateaued loop with an adjudicated result rather than adding a revision mechanism for an unsupported transition. Future delta context must retain the state-machine invariants on which a repair depends. Status: closed; runtime implementation remains a separate approval gate.

Promotion: incident — existing cross-agent-review-cycle guidance already requires unchanged context, evidence-based rejection, and stopping without chasing reviewer agreement.

## 2026-09-21 — Delta reviewer sought excluded caller context

A delta reviewer attempted Glob outside the harness read sandbox while checking an unchanged caller guarantee. The harness correctly invalidated that run. Retried with the unchanged caller excerpt explicitly included in the review context and the same repair baseline; the fresh valid review closed both required findings. No permission widening or provider substitution. Status: recovered, advisory-only terminal result.

Promotion: incident — existing delta-context and fail-closed retry instructions already cover this case.


## 2026-09-16 — CGMES save-refresh review boundaries

- Expected: scoped Opus reviews verify repairs against the production acquisition
  and projection boundaries.
- Actual: early findings inferred cache invalidation from a generation callback,
  and inferred raw timestamp storage from a fixture that skipped ingestion.
  Tracing the existing callback and reducer disproved those premises; actual
  rendered-grid assertions supplied the missing evidence. A separate conflicting
  stable-identity test exposed a stale-row restore fallback that needed the same
  guard as full-snapshot restoration.
- Impact and resolution: retained the established hydration owner and snapshot
  machinery; guarded both restoration paths and verified production-shaped save
  delivery and rendering. Scoped review converged to a Suggestion-only result.
  Declined a further live-producer timestamp scenario because it expands
  unchanged ingestion coverage without a demonstrated residual defect.
- Status: review gate complete; committed, pushed, and MR opened after the final
  combined-state check passed.
- Promotion: incident — existing review-skill rules already require tracing
  production boundaries, disproving false claims, and stopping at diminishing
  returns; no additional rule is needed.

## 2026-09-16 — Merge history review scope and retained guards

- Expected: the isolated reviewer consumes its bundle and repair reviews assess
  the changed behavior together with the stated unchanged guards.
- Actual: the first attempt requested a raw-worktree helper and was rejected by
  the harness. A fresh retry with summarized context completed. The repair
  review then missed an existing selected-identity reset and an existing
  malformed-timestamp test outside its delta.
- Impact and resolution: the failed attempt was not counted as review. Source
  inspection and production-path assertions disproved those later findings;
  real request-duplication and error-classification findings were repaired and
  independently re-reviewed. Kept the final outcome advisory rather than buying
  another round for agreement about unchanged guards or style.
- Status: automated loop closed at diminishing returns, with generated RTM
  synchronization separately blocked by existing inputs. No commit gate waived.
- Promotion: incident — existing isolation, evidence adjudication and delta
  context rules cover these cases; no additional rule is needed.

## 2026-09-16 — Sparse review evidence and baseline snapshots

Expected an isolated selected-file snapshot to support a baseline-relative design re-review. The first follow-up failed before Claude launched because the copied untracked evidence lay outside the temporary clone's sparse-checkout rules. Including the evidence directory in those rules made the harness snapshot indexable; retried in a fresh run directory. The project worktree was unaffected. For this uncommon review fixture, keep copied evidence inside the sparse selection.

Promotion: incident — temporary fixture setup issue; no general workflow rule needed.


## 2026-09-16 — Census stopped on a removed temporary worktree

Expected workspace census to report live reservations before implementation.
A stale temporary worktree path caused the census to exit before returning its
report. Read the private ledger and Git/worktree status directly, retained the
existing reservations, and claimed only the explicitly requested scope. No
worktree pruning was needed to implement the change.

Promotion: incident — existing direct evidence and claim-before-edit rules
covered recovery; no general skill change was needed.

## 2026-09-17 — Pi returned a bare CLEAN without inspection evidence

Expected a first-round Pi (`openai-codex/gpt-5.6-sol`) review of a staged
django-cast evaluation slice to show what it checked. The first attempt exited
normally with a parseable but evidence-free `CLEAN`, so it could not be
distinguished from a review that read nothing. A fresh run whose prompt required
an evidence section (files read, plus named checks with file:line support)
returned a substantive `CLEAN`, and the cycle stopped there. The cost was one
extra short run.

Promotion: pending — consider requiring an evidence section in the Codex/Pi
prompt contents of cross-agent-review-cycle; not changed in this session
because the skill edit was out of scope for the slice.

## 2026-09-19 — Distinguish verification from independent review

Expected the django-cast section-merge handoff to make its review status clear.
The initial handoff reported passing checks but had no independent review;
the user had to ask, then request the cycle. A later harness launch was blocked
by automatic approval review pending explicit authorization to send repository
content to Claude. No failed launch was counted as a review. After authorization,
the isolated review completed with suggestions only; documentation clarifications
were applied and redundant testing suggestions were deferred with rationale.
The cycle stopped as advisory rather than seeking a CLEAN label.

Status: resolved. State independent-review status explicitly at handoff and
distinguish a blocked launch from a completed review.

Promotion: incident — the existing cross-agent-review-cycle evidence, stopping,
and outcome-reporting rules already cover this; no additional skill rule needed.

## 2026-09-19 — Review evidence completed during an editor-lock review

Expected an isolated review of PATCH locks/logging with validation finishing
concurrently. The first attempt was invalidated for an out-of-bundle inspection;
retried fresh rather than treating it as a verdict. The valid review raised
verification warnings based on the initially pending checks. Completed Wagtail
edge runs disproved the mocked-log compatibility concern and satisfied the
completion criterion. Accepted a separate documentation-scope concern: PATCH
locks do not freeze publication. Documented that limitation and retained the
publish-lock policy decision in the backlog. A baseline-scoped re-review passed.

Status: resolved. Use completed check evidence when available and adjudicate
time-sensitive review claims against the final validation state.

Promotion: incident — existing evidence-adjudication, fresh-retry and delta-scope
rules cover this case; no new skill rule needed.

## 2026-09-19 — Make backend-specific test jobs fail on fallback

Expected the focused PostgreSQL job to prove real row locks. Local execution
first exposed three publication tests whose missing database markers were hidden
by warm Wagtail content-type caches; reproduced and fixed their declarations.
Independent review then identified that backend-specific skips could hide a
future SQLite fallback. Added an opt-in session guard, proved it fails under
SQLite and passes under PostgreSQL, and obtained a clean delta re-review.
Kept the first hosted run as a separate pending verification item.

Status: resolved locally and verified in hosted CI; PostgreSQL job passed.

Promotion: incident — the repair is encoded in this job's guard and development
docs; no broader review-skill rule is needed.

## 2026-09-19 — Identify test-only endpoints in review context

Expected a narrow CI compatibility review. The reviewer treated a test-only
upstream API experiment as a shipped consumer contract and proposed stabilizing
production behavior. Supplied the isolation boundary, clarified the test comment
and release note, and obtained a delta review confirming closure. Applied its
remaining prose-wrap suggestion and stopped without chasing a CLEAN label.

Status: resolved; review contexts should identify experiment-only mounting when
an assertion deliberately follows upstream runtime behavior.

Promotion: incident — existing scope and evidence rules suffice; no new skill
rule is needed.

## 2026-09-19 — Isolate preview state and its regression caches

Expected preview rendering to leave editorial data unchanged while creating
missing renditions. Full-matrix validation exposed rendition cache objects
surviving rolled-back test rows and a redundant save masking that leakage.
Isolated the test cache and used Wagtail's rendition getter without re-saving
existing rows. Independent review improved transport allowlisting, documented
private-hook compatibility coupling, and strengthened HTML/cache evidence.
The delta review left only proxy-TLS forwarding, implemented with regression
tests; stopped as advisory rather than seeking a CLEAN label.

Status: addressed in implementation/tests. One isolated review attempt was
rejected for out-of-scope inspection and was not counted as a completed review.

Promotion: incident — project-specific cache and preview tests encode the
lessons; existing review scope and stopping rules already cover the workflow.

## 2026-09-19 — Restore bootstrap rows between transactional test cases

Expected a session-scoped Wagtail bootstrap to support an expanded PostgreSQL
concurrency group. Transactional flushes removed the roots after the first
case; serialized rollback did not restore rows created after its snapshot.
Added an explicit restoring fixture before requesting editor actors, and used
it for both the existing and new editor concurrency cases. Independent review
prompted matching the session locale pair and allowing more lock-timeout margin.
The suggestion-only review was adjudicated without another agreement-seeking
round; claims about a missing docs target and file-order dependence were checked
against the existing label/build and pytest-django's test ordering.

Status: repaired and exercised in randomized combined PostgreSQL runs.

Promotion: incident — the shared project fixture and concurrency tests encode
the repair; existing review evidence and stopping rules already cover it.

## 2026-09-19 — Prove caller reachability for shared-helper findings

The comment-access review inferred that a shared None-target guard changed
creation/preview responses. Both callers already reject missing targets before
the helper. Added endpoint regressions proving the original error status,
no writes and no helper call; the focused re-review closed cleanly without an
unnecessary production rewrite. An initial assertion on the debug-only response
body was corrected while retaining the authorization-boundary assertions.

Status: resolved. Keep caller reachability evidence separate from a helper's
standalone input/output change when adjudicating compatibility findings.

Promotion: incident — the existing review skill's caller-chain and evidence
rules already cover this; project regressions preserve the concrete boundary.

## 2026-09-19 — Dependency cleanup needs every supported constraint boundary

Expected a fixed upstream dependency floor to permit removal of a local shim.
Focused tests on the oldest and newest framework environments and a clean
independent review missed an intermediate supported release's upper bound.
Hosted dependency resolution rejected the new floor before tests could run.
Existing-environment tests are not proof of installability across the supported
matrix: resolve every distinct framework dependency constraint when raising a
shared dependency floor, including intermediate supported branches.

Status: resolved after explicit approval to drop the end-of-life Wagtail 7.3
branch. Dependency metadata, hosted/local matrix and upgrade guidance now agree;
all retained CI jobs passed. The correction checked dependency resolution for
each retained hosted combination before pushing.

Promotion: incident — record the concrete missing validation here; no shared
skill change is made as part of this application's commit/CI task.

## 2026-09-19 — Review migration promises as contracts, not aspirations

A paged-feed research draft mixed non-expiring cursors with an unconditional
continuation/rollback promise, although key retirement can invalidate stored
links. Independent review exposed the contradiction before implementation.
The repair distinguishes mode-only rollback from key/decoder retirement and
defines safe-head recovery without claiming recovery of a client's position.
Parser fixtures, source evidence and installed-client tests now have separate
claim levels. Existing docs/cache concerns are tracked independently so feature
deferral cannot hide them.

Status: concept review closed with advisory clarifications; runtime and client
validation remain explicit implementation gates, not completed evidence.

Promotion: incident — these are concrete design contracts captured in the
project plan; the existing evidence and scoped re-review rules were sufficient.

## CI typing parity for custom Django expressions

Local Python 3.13 mypy accepted a list-valued custom Lookup return annotation,
including a cold-cache check, while CI's Python 3.14 environment rejected its
BaseExpression override. Returning parameter tuples preserved SQL semantics and
matched the stub contract. Check the locked CI interpreter/environment when
diagnosing type-check discrepancies; clearing the cache alone is not evidence
of environment parity. The focused independent repair review closed cleanly.

Promotion: incident — project-specific compatibility repair; no additional
review-loop rule is warranted.

## 2026-09-23 — A Codex review harness has to prove its own boundary

Building `codex-review-loop` (gpt-6-sol through the Codex CLI) turned up three
assumptions that were false on the installed Codex 0.156.1:

- `--sandbox read-only` restricts writes, not reads: a file outside the working
  directory was readable. A named permission profile (`:minimal`, the review
  root, explicit denies for the temporary directories) confines reads; with
  `--ignore-user-config` the model still had account app tools, subagents and
  image generation until each was disabled.
- `codex exec --json` names no model and did not show a subagent spawn. The
  session record under `$CODEX_HOME/sessions` holds both, so the verdict is
  accepted only after that record proves the model and the tools.
- The npm `codex` launcher exits 0 after its native child dies of SIGTERM: its
  own handler swallows the signal it re-raises. The harness runs the native
  binary, whose status is the signal's.

A boundary canary using the production review instruction passed vacuously: a
compliant reviewer never tried to leave its root. The canary drives the
production command with a canary instruction and requires recorded attempts.

Five read-only gpt-6-sol rounds: 5 Critical and 4 Warning in total, every one a
fail-open or missing-result path, several introduced by the previous repair
(a liveness sample standing in for signal delivery, then 143 standing in for a
signal death, then the launcher's exit 0). The fifth round closed clean.

Promotion: promoted — codex-review-loop, "Read boundary", "What makes a
verdict count" and "Lifecycle and timing"; cross-agent-review-cycle, Codex
branch pointer to the harness.

## 2026-09-23 — A mutation run proved nothing because the repair did not build

In the emerge-ios Merge result series, a cumulative-review repair did not
compile. The mutation run swapped in a mutated copy that did compile, and its
test failed, so the run read as "caught". It was evidence about code that could
not run. Redone against a build verified first; every later mutation run built
the unmutated tree before mutating.

Promotion: promoted - cross-agent-review-cycle, "Judging the evidence a repair offers".

## 2026-09-24 — Behavior slices drew a docs Warning when docs were planned last

In an emerge frontend series where the user put docs and the single changelog
entry in the final slice, the codex-review-loop reviewer raised "no docs or
release note" as a Warning on two behavior slices, because the review
instruction includes the documentation rule and the context did not say docs
were deferred. Both were rejected under the user's slice plan; the docs slice
and the cumulative review covered them.
Follow-up: when docs are deliberately sequenced into a later slice, say so in
the slice's context file so the reviewer does not spend a finding on it.

Promotion: incident

## 2026-09-26 — Viewer consolidation measurement narrowed the plan

The emerge log-viewer handoff expected a large duplicate-path reduction. Reading
both adapters and measuring exact blocks showed the hard filtering and layout
components were already shared; remaining savings were modest. The first plan
review caught the old largest-gain claim still in the backlog and a title that
covered less than its slice table. Updated the goal, parent plan and backlog
together; the repair review confirmed both required corrections. Existing
measurement and documentation-sync rules cover this case; no new gate is needed.

Promotion: incident

## 2026-09-26 — Qt setter order during shared widget setup

Expected a construction-only extraction to preserve input behavior. The full
viewer suite showed that moving read-only setup after explicit selection flags
removed keyboard selection: Qt resets those flags in setReadOnly. Restored
explicit interaction flags after the shared setup and retained stylesheet
append order. Existing end-to-end assertions caught the change; keep setter
side effects in the ordering audit even when all final calls remain present.
Promotion: incident

## 2026-09-27 — Verify rendered behavior against saved source

Expected the Connect & Score implementer report to describe the saved Qt code.
It claimed an interpolated animation marker that was absent from paintEvent;
passing interaction tests covered results but not that presentation behavior.
Parent source inspection and narrow-window captures found the mismatch and
palette/clipping defects before the independent review gate. The implementer
was sent a bounded repair with a presentation regression test. Existing
cross-agent-review-cycle instructions already require checking actual edits
and independently rerunning checks; no additional rule is needed.
Promotion: incident

## 2026-09-27 — Shared feed caches need a final response boundary

An endpoint plan keyed the origin cache by active language but left downstream
language negotiation ambiguous. Review led to fixed rendering locale/timezone.
The repair's no-store fallback then lacked a mechanism for headers added after
the view; a delta review caught it. Name the actual response-finalization hook
when promising post-middleware safety, including insertion timing and 304s.
The plan now specifies an opt-in outermost hook and explicit full-site-cache
incompatibility. Review closed with advisory clarifications, not a CLEAN verdict.

The earlier apparent Claude logout was limited to the restricted calling
session: normal-terminal authentication worked, and restoring session access
made the same CLI authentication visible without another login.

Promotion: incident — these are recorded endpoint contracts and environment
diagnostics; existing scoped-review and evidence rules were sufficient.

## 2026-09-27 — Recover an interrupted implementation from disk, not its report

A Claude implementation stopped after a provider DNS failure with source and
tests already saved. Its full-suite log exposed a LocaleMiddleware test-state
leak that focused checks had missed. A bounded fresh Claude invocation repaired
the fixture; independent full validation and a different-family review then
closed the slice. The review harness also required the project's modern Python,
not the older system interpreter. No failed invocation counted as a verdict.

Promotion: incident — existing implementer supervision, independent verification
and fail-closed review rules already prescribe these recovery steps.

## 2026-09-27 — Verify a reviewer's framework premise before changing behavior

A feed repair review claimed Django ignored If-Unmodified-Since without a
Last-Modified value. The implementer challenged it; inspecting the installed
helper and exercising the public middleware stack across supported dependency
bounds proved the premise false. Kept the correct behavior, clarified its
documentation and supplied the framework source to the final delta reviewer.
The four earlier HTTP/cache findings were independently verified as repaired.

Promotion: incident — the existing finding-adjudication and primary-evidence
rules apply; a valid reviewer verdict is evidence to assess, not an instruction
to change correct behavior.

## 2026-10-02 — CGMES retry-backoff review

Expected: the read-count regression executes a listing before testing retry admission. Actual: the first test setup omitted the runtime issue clock, so the worker failed before the counted listing. Fixed the setup with the existing IssueMarkClock and reran against unchanged production code; the repeated-read assertion then reproduced the bug. Opus 5.5 suggested long-TTL and queued-ownership evidence; both added and the repair review closed clean. No new workflow rule is needed: the existing requirement to prove an injected failure executed covers this case.

Promotion: incident.

## 2026-10-02 — Shared backlog staging during CGMES closeout

Expected: staging the closeout files includes only this task. Actual: another session edited the shared backlog while acceptance ran, and a whole-file add captured two unrelated rows. The independent reviewer caught the scope leak before commit. Rebuilt the backlog index entry from HEAD with only this task row removed, preserving unrelated working-tree hunks, then reviewed the exact repaired staged snapshot in an isolated clone. Existing commit-workflow scope rules cover this; checking staged hunks is the required application.

Promotion: incident.

## 2026-10-02 — Plan reviews need a concrete review input

Expected: a context-only plan review over a clean implementation worktree. Actual: the Claude harness correctly refused an empty change bundle. Impact: no valid review occurred. Resolution: placed the plan as a diff in a private repository copy, then used the usual whole-plan and repair-delta gates without putting tooling artifacts in the product repository. Status: resolved.
Promotion: incident; the harness already documents the non-empty-change requirement.

## 2026-10-02 — Authentication integration review scope and UI timing

Expected: scoped repair reviews and complete integration checks cover only the authored slice while shared user work remains separate. Actual: a root review included a pre-existing empty runtime lock and flagged it as part of the repair; isolated docs delta review could not combine staged-only with a prior baseline. Kept the user file outside the index/commits, adjudicated the false scope finding with Git evidence, and reviewed the exact shared documentation index in a private clone. Full-suite integration also exposed lightweight CGMES supervisor lookup and stale progress recipes missed by focused suites; repaired them and obtained an independent clean review. Unchanged result-view timing/layout cases passed in isolation and the final rebased full gate. Status: resolved; no accepted required finding remains.

Promotion: incident; existing exact-scope, isolated-review and full-integration rules cover the failures.

## 2026-10-02 — Results-spinner full-suite validation

Expected: the full frontend gate validates the reviewed spinner fix. Actual: two sixteen-worker runs each timed out in a different existing Model Improvement permission test while awaiting its initial catalogue; the file passed in isolation. Impact: the full gate remained incomplete despite clean review and passing spinner regressions. Resolution: retained the full test selection and coverage thresholds, reran with eight workers, and obtained a complete passing gate. No change was made to the permission tests or default concurrency. Status: resolved for this slice; these results alone do not establish the catalogue timeout's cause.

Promotion: incident — existing rules require full validation and evidence before declaring a failure unrelated; no new default concurrency rule is justified.

## 2026-10-03 — Configuration opening progress review

Expected: replacing a blocking wait cursor with the shared Qt loading modal preserves browser lifetime and replay ordering. Actual: the first passing full gate missed owner deletion during the nested event loop, cancellation recording an unpublished browser, prerequisite replay openings, and stale workflow documentation. Independent Sol review reproduced these paths; guarded cleanup, outcome-aware recording, serialization of all browser-opening actions, and complete documentation corrections resolved them. Repair regressions were independently shown to fail against the earlier implementation. The scoped cycle closed clean. Status: resolved.

Promotion: incident — existing independent review, production-caller regression and documentation-sync rules cover these omissions; no new skill rule is required.

## 2026-10-03 — Sandbox scale integration: cached fit ownership

Expected: returning to an earlier scale preserves opening-size ownership for a later new scale. Actual: cached results geometry restored the window without updating its fit marker, so the next scale change skipped the fit. Independent Sol HIGH review found the mismatch; Sol LOW repair synchronized the marker through the shared restoration hook. A fresh125 comparison after100→150→100→125 fails against the old tree and passes after repair; independent scoped review closed CLEAN. Existing caller and grip guards stayed intact. Narrow test selection initially named a nonexistent module and was corrected before accepting evidence. Status: resolved.

Promotion: incident — existing state-ownership review, meaningful regression and exact validation-selection rules cover this; no new skill rule needed.

## 2026-10-04 — Integration staging failure caught before push

A merge had already staged a deletion. Explicitly adding all HEAD-diff paths failed on that absent, already-staged file; a shell without fail-fast then continued to commit the earlier index. Committed-tree equality caught omitted final metadata before push. Preserved the true merge and added a reviewed metadata commit, with final tree equality verified. Use fail-fast around stage/tree/commit and stage only remaining worktree deltas in an already-staged merge. No history rewrite or unreviewed tree was pushed.

## 2026-10-04 — Shared documentation remote advanced during integration

A task-only reviewed docs commit could not fast-forward remote main after a disjoint committed plan update arrived. Merged remote main without rewriting history or staging the existing unrelated dirty plan. Compared the staged task-doc patch byte-for-byte with the reviewed commit and verified all other committed files matched remote main, rebuilt docs, then pushed only task commit and its reconciliation merge. Remote refresh before docs publication avoids an unnecessary rejected push.

## 2026-10-04 — Catalogue rebuilds must preserve shown validation

The full sandbox review reproduced a delayed operation catalogue rebuilding an already-marked edit selector without restoring its error mark. The same Process catalogue path reproduced the loss. Narrow held-response regressions failed before the repair; rechecking shown errors after both catalogue applications restored the marks, and independent Sol HIGH delta review closed CLEAN. The size gate also required one controller to own new field-error presentation; the old path was removed and the allowance lowered by the tool. Composition measurements initially missed an untracked helper and one archive invocation used a subdirectory-relative path; corrected snapshots included the staged helper and an explicit root archive before reporting package deltas.

Promotion: incident — existing state-ownership, async regression, size and exact-evidence rules cover these events; no new skill rule needed.

## 2026-10-06 — Review run directories in a scratchpad shared by parallel agents

Expected: a run directory named after the round (`review/r1`) is fresh. Actual: several subagents share one session scratchpad; another agent's `review/r1` already existed, so the harness refused it ("run directory must be new or empty") and a context file written next to it vanished before the retry. No review ran against wrong content and no foreign result was read; the retry used a slice-named subdirectory. Use a directory unique to the slice (or `mktemp -d`) for both context files and run directories when agents share a scratchpad.

Promotion: incident — the skill already says to create a fresh run directory with `mktemp -d`; following it avoids this.
