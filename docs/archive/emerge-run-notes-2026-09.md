# Archive: Per-Run Project Notes, 2026-09

These are per-run execution notes from the emerge frontend, Traefik, and
django-cast work. They were written into the shared agent/process log, which the
log's own header reserves for reusable cross-project lessons; project execution
detail belongs in that project's own workflow log.

They are preserved verbatim rather than rewritten. Several are compressed to the
point of being hard to read (`Fullcheck10314/135.26s types430 domain100`), which
is the other reason they were moved: run metrics are not a lesson, and they made
the active log unmineable.

The reusable lessons that were in them have been distilled into dated entries in
`../review-cycle-log.md`. If these notes belong in the emerge repository's own
workflow log, move them there; nothing here is referenced by a skill.

## 2026-09-02 - Bind Loading Feedback to Surface, Scope, and Attempt

- Repo: Emerge Process data loading feedback.
- Implementer: Codex.
- Reviewer: Pi using `openai-codex/gpt-5.6-sol`.
- Expected: an application-owned presentation model would give each Process
  surface truthful freshness, retry, outcome, and accessibility feedback while
  rejecting stale work.
- Actual: the first review found that production projection bypassed part of
  the per-surface composition, inactive surfaces could announce accessibility
  changes, prior-data freshness was too coarse, and coarse liveness age began
  at widget display rather than the current attempt. A narrow second review
  found the headless accessibility fallback was not sufficiently isolated from
  production inactive-window behavior.
- Impact: passing component tests could still permit cross-surface outcome
  leakage, stale freshness claims, reset liveness timing, or duplicate screen
  reader announcements.
- Fix or follow-up: carry immutable Process, surface, lifecycle, exact request
  scope, attempt, generation, and start-time identity through controller truth;
  compose each surface before projection; and announce only changed active-
  surface presentations, with headless fallbacks explicitly platform-gated.
- Status: resolved; accepted findings were repaired and the third, strictly
  narrow review returned clean with no remaining findings.

## 2026-09-07 - Frontend isolation and review evidence must cover execution

- Repo: emerge, frontend maintainability implementation (still in progress).
- Expected: a domain/application path selection stayed Qt-free; clean unchanged
  source implied the domain coverage floor was already met.
- Actual: the Qt pytest plugin imported Qt before collection and shared fixtures
  imported concrete adapters. An isolated original-HEAD run also reproduced the
  same 26 uncovered domain lines as the first integrated batch.
- Fix: disable the Qt plugin for the real lane and verify collection through
  finalizers in a fresh full-lane subprocess. Keep fixture isolation inputs pure
  and pin production constant/stub equivalence in the adapter lane. Add meaningful
  edge tests rather than lower the coverage floor or assume a baseline pass.
- Review evidence: supervised Opus 5 flagged three practical warnings; repairs
  are awaiting bounded re-review. Two innocent local `token` assignments were
  redacted from source evidence. Renaming those issuance locals removes the
  false-positive without weakening credential redaction. No CLEAN claim yet.
- Integration lesson: after executor admission changes, a task-ledger row is not
  proof that the backend worker started. Tests should await the actual milestone.
- Status: implementation and review continue; record the final disposition later.

### Follow-up: profile concurrency limits need operator-path evidence

- The bounded second Opus 5 review verified the initial three warnings and
  returned one new Warning plus three Suggestions, with no hidden or truncated
  evidence. Counting obsolete workers correctly exposed an untested operator
  path: saturation silently fell back to set detail.
- Preserve the scheduling bound while testing the actual selected detail pane
  under saturation; accepted requests must either progress or report a truthful
  state. This repair is ongoing alongside a canonical family-alias correction.
- Test-helper organization is deferred as low-impact; no CLEAN claim or another
  agreement-seeking pass follows merely from that suggestion.

### Follow-up: close the broad review when only bounded suggestions remain

- Third supervised Opus 5 review verified the saturated-profile repair and
  application terminal ownership: zero Critical/Warning, four Suggestions, no
  omissions/redactions/truncation. Verdict remains ISSUES, accepted advisory.
- Stop the broad cycle at diminishing returns. Apply small guard/diagnostics/API
  improvements without another pass merely for agreement. A concrete removed-
  Process resolver discrepancy gets a regression and bounded scrutiny with the
  next lifecycle integration; unrelated test organization remains deferred.
- Integrated S6 snapshot passes its unchanged domain100% floor. Subsequent
  residency implementation is separate and must earn its own evidence/review.

### Frontend residency: test enabled composition and restoration effects

- An explicit eager embedding profile preserves supported tests and simulation,
  but its broad suite cannot prove the deployed residency path. Real enabled
  window tests found shared-cap accounting, sliced-apply pins and failed-read
  revisit gaps that isolated policy tests could not expose.
- Transaction rollback restored models yet changed the selected tab while
  rebuilding a view. Tests must drain deferred Qt deletion, check selection and
  readiness, and cover explicit reconstruction after rollback itself fails.
- Retained-view counts must distinguish full views from lightweight placeholders.
  Measure application models and raw task/Merge payloads as well as widgets;
  successful reactivation counters prevent a falsely cheap failed-load replay.
- A small resolver cleanup changed a diagnostic from nonblocking success context
  into a session safety latch. Regression tests should use the real downstream
  gate, not merely assert that a diagnostic callback was invoked. Required
  repairs receive bounded independent re-review even after a prior advisory stop.

2026-09-07 — Frontend maintainability S8 repair verification: keep cold registration separate from full-view installation success. A rollback test returning False can pass before its injected failure executes; assert the fault callback was reached and pair it with successful cold single/group transactions. Reuse canonical table-plan scopes in both hydration and eviction. For async operation pins, prove ownership through queued delivery and second worker submissions, and assert progress/cursor cleanup separately from pin settlement. Preserve an exact prior-review source snapshot so repair re-review can omit unrelated historical test moves without omitting the actual repair delta. A regression test that also passes old code is behavioral preservation evidence, not a reproduced defect.

2026-09-07 — Final maintainability repair review: explicit claude-opus-5 returned ISSUES with zero Critical/Warning and three Suggestions after 658.317s. Accepted the required repairs and stopped advisory, not CLEAN. Restored two misplaced docstrings without another agreement pass; deferred timestamp memoization and 10 Hz catalog pin scanning to representative measurements. Inspected one false-positive redaction of an unchanged diagnostic key, with no omissions/truncations/forbidden tool use. The final source replay reconfirmed the measured ownership bounds. User review/native acceptance remain open; no commits or Jira writes.

2026-09-07 — Manual replacement native freeze: a shown QTableWidget with ResizeToContents remeasured the table on each setItem. Native sample2420/2426 in that path; deterministic80row delegate calls315280 before/560 after. Freeze header geometry during complete result insertion and preserve sorting/redraw settings on failure. Do not convert inherited disabled redraw to an explicit table freeze: toggle updates only if initially enabled. Parent-reenable regression caught that Qt distinction. Focused Opus5 returned0Critical/Warning/1Suggestion271.578s, no redactions/omissions; tiny guard applied and final10242tests passed. Stop advisory without another agreement pass. Final native retry remains pending; no live app restart or code commit/deployment performed.

- 2026-09-08 frontend recovery metadata: small GPT-5.6 Sol slice + direct Opus 5 xhigh review converged advisory (0 Critical/Warning). A regression against a removed retention map remains identifier-specific; retarget it when the owner moves. Comment-only clarification verified by AST equality and lint; no repeated full pipeline or agreement-only review. Complete.

- 2026-09-08 typed hydration forwarding: Opus 5 xhigh review advisory (0 required findings); protocol default drift and probe-count-coupled tests improved locally. Keep actual cache enabled in wiring tests. All-six pre/post-call checks and explicit fault-execution assertions pass. Production stayed byte-identical to full-check/review snapshot; test-only repairs verified in focused and guarded lanes without an agreement-only review. Separate cache client bypass reproduced on old/new proxy and selected as next slice.

2026-09-08 frontend shared-cache authorization slice: direct claude-opus-5 xhigh via supervised harness, initial1Warning+5Suggestions, focusedrepair Suggestionsonly. Stale fallback-only docstrings were the required repair; marker-triggered warm lookup and observed read-lock barrier materially strengthened tests. Runtime AST comparison established doc/test-only repair after full pipeline; targeted+guarded lanes rerun. Stop advisory, not CLEAN; no third pass for wrap/consumer-doc nits. Callback documentation prompted checking actual live predicates, not speculative lock redesign. Faithful snapshots kept unrelated shared-doc dirt out of both reviews.

2026-09-08 queued targeted demand: supervised claude-opus-5 xhigh initial ISSUES0CW4S. Completed queue ownership removal + exact existing test assertion migration. Coordinator caught whole-map emptiness weakening into single-key absence before review and requested count-preserving queries. Review useful docs rationale/lock wording/stale plan evidence fixed; API keyword-only style declined. Stop advisory, not CLEAN, no agreement-only pass. All runtime ASTs/tests/config identical to frozen full check after comment-only repair. Avoid carrying obsolete line-number evidence into remaining-work plan.

### 2026-09-08 frontend R2d operation ownership

Opus5 xhigh initial1W2S, focused2S; required stale remaining-work Warning fixed and reviewed, final tiny wording fixes applied, advisory NOT CLEAN. No scope omissions. Update all current-state status paragraphs before initial review; historical R2 status can remain dated. Preserve first-issue order separately from reservation order and directly test id-only vs full-record retirement; controlled mutations were detected. Full check10295 passed using private TMPDIR after shared macOS mktemp collision before coverage began; no shared file deletion or unrelated recipe fix. Repair552focused/3059guarded, runtime AST/config identical. Code ccb56f65/docs2924fd6.

2026-09-08 backend-review frontend fixes: three GPT-5.6 Sol workers, two supervised direct Opus5 xhigh reviews. Initial1Warning7Suggestions; focused0Critical0Warning6Suggestions, final advisory NOT CLEAN. Cold refresh must clear non-visible observation references before dropping model allocation. Reconcile already rearms pending identity retries; review suggestion missed caller timer. Freeze all worker edits before full-check collection: concurrent test edits produced stale assertions. Verify saved signatures against worker reports; claimed required keyword remained optional until final correction. Fullcheck10264 domain100%, non-domain91.39%; final signature repair97focused+mypy. Stop after bounded requested review, defer instrumentation/diagnostic nits; no commits.

### 2026-09-08 frontend R2e diagnostic ownership

Opus5 xhigh initial ISSUES0CW3S349.769s, metadata clean. Applied doc clarity/wrap and diagnostic-only snapshot assertion; deferred speculative internal paired-field redesign because all writers encapsulated and invariants maintained (sort tuple unique Process key makes claimed context tie impossible). Advisory NOT CLEAN; no agreement-only pass. Fullcheck10301/155.86s, types430 domain100 non91.38,617focused,112E2E; controlledcorrelation/order mutations detected with executionmarkers. Repair557focused/3064guarded; runtimeASTidentical. Coordinator took over two tiny doc/test repairs after interrupted worker repairturn produced no edits. Code df1e0a21/docs8c8270e.

### 2026-09-08 frontend R2f delayed ownership

Initial integration caught reservation leak from id-only operation retire in combined cancellation and overstrong dual-id scheduler-failure cleanup. Both repaired before Opus; controlled mutations demonstrated tests detect them plus missing active-op guard. Opus5xhigh ISSUES0CW3S287.054s, no metadata omissions. Applied docwrap and successful stored-handle assertion/removed unused testhelper args; speculative displacedtimerbehavior deferred pendingrepro sincebaselineequivalent. Advisory NOT CLEAN. Fullcheck10307/159.84s types430 domain100 non91.39;623focused112E2E;repair563focused3070guarded, ASTidentical. Code43361016/docs8a6411b. Use actual prek scopedhooks before fullcheck to catch repositoryformat flags; always wrap docstrings before initialreview.

### 2026-09-08 frontend R2g settlement ownership

InitialOpus5xhigh0C1W3S296.053s; focused0CW4S270.308s, metadata clean. Coordinator first caught grouping/shadowmap and stale bind-rejection H2 consumption; initial review caught sibling None-return rejection. Fix coupled success/failure branches together when adding reentry checks. Moving independent maps into shared immutable entries changes synchronization risk: use existing lock for new settlement accesses, keep observation/callback effects outside, verify with injected lock assertions and mutation. Restore original recovery-ticket predicate, not only sentinel equality. Four material repair mutations executed and caught. Focused re-review resolved required Warning; useful ordinary intent-rejection test/comments applied, already-locked reactivation suggestion factually rejected. Advisory NOT CLEAN; no agreement-only third pass. Fullcheck10314/135.26s types430 domain100 non91.40;630focused112E2E; final571focused3075guarded runtimeASTidentical. Codef43f589e/docsca29e614. Preserved user macOS venv mitigation/note without stopping tests; durable test-infrastructure slice next.

### 2026-09-08 frontend M1 macOS xdist titles

Sol runtimehelper patches actual __channelexec__ WorkerInteractor globals, not separately imported xdist.remote. Real2worker identity probe passes4cases; disabledhookcontrol fails4 evenwithpreservedvendorpatch. Scopedhelper keeps applicationsetproctitle/defaultparallel unchanged. Opus5xhigh initial1W1S312.848s; focused1W1S140.367s after following suggestedslowmarker; final0CW2S81.107s after explicit90s timeout. Derive enclosing subprocess watchdog directly from sharedchildbudget; duration-classification slow marker can be removed by later reconciliation and should not own timeout policy. FinalS constant applied/tested; stopadvisory NOT CLEAN. Thirdreview evidence files had become tracked scratchbaseline, so bundle onlyshowedhunks: corrected private snapshot helper to stage code/docs only, remove evidence fromscratchindex and retain full current evidence untracked eachround; verified fullbytecopy/indexstate. Limitation disclosed; finalrequiredmarkerrepair independently checked againstactualcollection90s/not-slow;no4thagreementpass. Fullcheck10320/131.64s types430 domain100 non91.40;33focused112E2E3075guarded;final22focused2.97s docs/hooks/runtimeASTidentical. Codee72f5a17/docsfa88430c. No active tests stopped; vendorpatch/note preserved; desktopfreezecausation stillopen.
