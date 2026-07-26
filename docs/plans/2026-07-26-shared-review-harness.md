# Review Harness — Safety Parity Now, Extraction Later

Status: draft for review (round 4)
Date: 2026-07-26

## Problem

`claude/skills/pi-review-loop/pi_review_loop/` and
`codex/skills/claude-review-loop/claude_review_loop/` implement the same
harness twice: spawn a reviewer in its own process group, observe a JSON event
stream without wedging, detect stalls, reap on every exit path, serialize a
structured result, and serialize concurrent reviews behind a lock.

Measured duplication (differing lines, `diff | grep -c '^[<>]'`):

| module  | pi  | claude | differing |
|---------|-----|--------|-----------|
| states  | 14  | 14     | 0         |
| result  | 34  | 42     | 14        |
| runner  | 213 | 264    | 107       |
| monitor | 65  | 167    | 138       |
| bundle  | 155 | 279    | 198       |
| lock    | 192 | 228    | 218       |
| verdict | 66  | 59     | 95        |
| model   | 173 | 14     | 173       |
| redact  | —   | 229    | absent    |

The cost is not aesthetic. Hardening gets applied to one package and silently
not the other. Verified gaps in the **Pi** harness, which is the mandatory gate
in most repositories recorded in `docs/review-cycle-log.md` and which sends the
working-tree diff to a third-party provider:

- **No redaction at all.** `pi_review_loop/bundle.py:99` sends decoded untracked
  content directly. The Claude harness detects secret-looking paths and omits
  their contents before egress (`redact.py`, 229 lines).
- **Unhardened git invocation.** `pi_review_loop/bundle.py:18` is a text-mode
  `subprocess.run(["git", *args])`. The Claude harness runs git with
  `--no-ext-diff --no-textconv --no-color --default-prefix` so a
  repository-configured textconv or external diff driver cannot execute during
  bundle construction, and decodes output byte-exactly.
- **No symlink or special-file refusal** (`stat.S_ISLNK`/`S_ISREG`).
- **A weaker lock.** Pi has atomic `mkdir` but zero `fcntl` advisory guard, no
  owner token, no unique stale tombstone, and no ownership-checked update or
  release (`pi_review_loop/lock.py:20,140,152`). Claude has all four
  (`claude_review_loop/lock.py:5,23,153`).
- **A weaker lifecycle.** Pi has zero `KeyboardInterrupt` handling
  (`pi_review_loop/runner.py:167`); Claude catches it in two places
  (`claude_review_loop/runner.py:193`). Claude re-checks process-group liveness
  after a wrapper exits (`runner.py:33`); Pi returns once the leader is reaped
  (`runner.py:22`).
- **No trust boundary.** Claude's system instruction defines an untrusted
  repository-evidence boundary (`claude_review_loop/cli.py:18`); the Pi
  instruction has no equivalent rule (`pi_review_loop/cli.py:16`).

The first four `2026-07-10 - Consolidated:` harness-hardening entries in the
review log record this work as done. It is done once — on the path that also
runs under OS isolation — and not on the path that egresses to an external
provider.

## Strategy

Round 1 review established that a five-phase structural consolidation
over-reaches: the two locks, bundles, and runners differ in *semantics*, not
just in code, so extracting them without written contracts trades visible
duplication for hidden adapter configuration and migration risk.

This plan therefore does the safety work first and **stops at a reassessment
gate**. Structural extraction of `result`, `bundle`, `lock`, `monitor`, and
`runner` is deferred to a successor plan that may only be written once the
behavior contracts in the gate exist. Phases 1–4 are each independently
valuable and independently revertable, and none of them requires the extraction
to happen at all.

## Non-goals

- Restructuring `docs/review-cycle-log.md`. Separate change.
- Deduplicating non-harness assets (`sample_tmux_frames.py`,
  `mermaid-marked2-markdown/references/`). Unrelated to harness safety;
  separate plan.
- Packaging or distributing either harness.
- Changing review policy: pinned models, cycle caps, fail-closed rules, exit
  codes, CLI flag surfaces.
- Merging the two CLIs. `pi-review-loop` and `claude-review-loop` stay separate
  entry points with separate skills.
- Unifying the two `result.json` schemas. Both field sets are published and one
  is documented in `claude-review-loop/SKILL.md:187`; a union would be a schema
  migration, not a refactor.
- Touching `codex/skills/opus-review-loop/` beyond keeping its shim working.

## Locked decisions

1. **Shared code lives at `shared/review_harness/`** in the repository root.
   Neither skill owns the other's internals.
2. **Entry points resolve the repository root from
   `os.path.realpath(__file__)`**, walking up to the directory containing
   `shared/`. chezmoi deploys each skill as a symlink, so `__file__` is a
   symlinked path and `realpath` is mandatory. A missing `shared/` must produce
   an actionable installation error, never a bare `ImportError`. Both bins
   currently add only their own skill root
   (`pi-review-loop:5`, `claude-review-loop:5`), so this bootstrap is a
   **prerequisite of Phase 1**, not a later cleanup.
3. **Pi changes are hardening; Claude changes are limited to three named
   items.** Most behavior change here is deliberate Pi hardening: redaction,
   hardened git, symlink refusal, lock guard/token/tombstone, interrupt
   handling, and the trust boundary. Otherwise the Claude harness changes only
   by import path, with a compatibility re-export of `claude_review_loop.redact`
   through Phase 1 — with three exceptions, all found during this plan's review
   and all defects rather than refactors:
   - the open-by-pathname race in `claude_review_loop/bundle.py:129-140`
     (Phase 1),
   - the missing process-group check on natural leader exit
     (`runner.py:176-177`, Phase 3),
   - the deployment barrier check (Phase 0).

   Fixing a defect on one side only is the exact failure this plan exists to
   end, so both harnesses get all three.
4. **Hardening is declared, never smuggled.** Each Pi behavior change is listed
   in its phase, tested explicitly, and recorded in the skill documentation. It
   is not described as refactoring.
5. **Lock layouts are preserved.** Pi's `--lock-dir` is a pool containing
   `slot-N`; Claude's `--lock-dir` is the lock directory itself. Phase 2
   hardens each Pi slot *in place* and does not restyle Claude as a one-slot
   pool — doing so would move Claude's lock path and could let an old
   direct-lock holder and a new `slot-0` holder run concurrently during
   migration.
6. **Coverage is tracked as a contract matrix, not a test count.** Moving a
   shared test to run once legitimately reduces the collected total. Each phase
   records expected per-suite counts and the named behaviors each suite still
   asserts. Baseline: 108 Pi, 158 Claude (157 passed, 1 skipped).
7. **Documentation is phase acceptance.** Any phase that changes behavior or
   deployment structure updates the affected `SKILL.md` and README in the same
   commit.
8. **Implementation happens in a separate git worktree.** The canonical
   `~/projects/agent-stuff` checkout is the absolute path every skill invokes;
   editing it in place breaks reviews running in other sessions.

## Phases

Each phase is one commit, ends with `just check` green, and is revertable
without touching earlier phases.

### Phase 0 — Enforcement first

Build the check harness before changing code, so every later phase is gated.

- Add a root `justfile` with `just check`: both harness suites via
  `uv run --with pytest python -m pytest -q`, `python3 -m compileall` over every
  package, a `diff` of the two mirrored `cross-agent-review-cycle/SKILL.md`
  files, and a README-inventory check.
- The inventory check compares `(agent, skill)` pairs, not skill names. Seven
  pairs are currently missing: `claude/tmux-transient-ui-verify`,
  `codex/tmux-transient-ui-verify`, `codex/mermaid-marked2-markdown`,
  `codex/opus-review-loop`, `codex/parity-improve`, `codex/pipy-parity-loop`,
  `codex/workspace-wrap-up`. A name-only check misses the Codex Mermaid skill
  because the Claude row already matches.

- Add a **deployment barrier** to both CLIs, with two properties that a naive
  start-up check does not have:

  1. **One canonical path, not per-harness.** The default lock directories
     differ (`~/.cache/pi-review-loop/locks` versus
     `~/.cache/claude-review-loop/lock`), so a barrier derived from `--lock-dir`
     cannot block both harnesses with one file. Both CLIs check
     `~/.cache/agent-stuff-review/BARRIER`, independent of `--lock-dir`, with a
     `--barrier-file` override for tests.
  2. **Checked at admission, not only at startup.** Both CLIs build their
     bundles before acquiring a lock (`pi cli.py:97` vs `149`;
     `claude cli.py:212` vs `243`), so a startup-only check leaves a window as
     wide as bundle construction: an invocation sees no barrier, spends seconds
     bundling, and acquires a slot after the operator has already observed empty
     lock namespaces. The barrier is therefore checked **twice** — once before
     bundling, and again immediately after lock acquisition and before spawning
     the reviewer. An invocation that acquires a slot while the barrier exists
     releases it and exits with the distinct barrier code.

  With the post-lock check, "barrier established" plus "lock namespaces drained"
  is a real guarantee that no reviewer will start: anything that acquired before
  the barrier is what draining waits for, and anything acquiring after it aborts.

Acceptance: `just check` passes on a clean tree; it fails if either mirror is
edited on one side only, or a skill directory exists without a matching
`(agent, skill)` inventory row. A pre-existing barrier makes both CLIs refuse to
start; a barrier created *after* startup but before lock acquisition makes both
CLIs release the slot and exit with the barrier code — tested on both.

Test accounting: Pi 108 → 108 + 2 (pre-bundle barrier, post-lock barrier);
Claude 158 → 158 + 2. Retained contracts, both suites: exit-code mapping,
lock acquisition and release, and no-changes refusal all still asserted. Record
actual counts in the commit message.

### Phase 1 — Path bootstrap, shared redaction, hardened git

- **Prerequisite, same commit:** repository-root resolution in both bins per
  locked decision 2, an actionable error when `shared/` is absent, a test that
  executes a bin through a symlink, and confirmation that each skill's suite
  still runs from its own directory.
- Move `claude_review_loop/redact.py` to `shared/review_harness/redact.py`
  unchanged. Keep `claude_review_loop.redact` as a re-export for this phase.
- Extract the hardened git invocation into `shared/review_harness/gitio.py`:
  the flag set plus byte-exact decoding without universal-newline conversion.
- Adopt both in `pi_review_loop/bundle.py`, and add symlink and special-file
  refusal.
- **Fix the open-by-pathname race in both harnesses.** The existing Claude code
  calls `os.lstat(full)` and then opens the same path by name
  (`claude_review_loop/bundle.py:129-140`), so a regular file can be swapped for
  a symlink or FIFO between the check and the read. Copying that pattern into Pi
  would copy the bug. The shared helper must open with `O_NOFOLLOW|O_NONBLOCK`,
  `fstat` the descriptor, and read from the descriptor — never re-resolve the
  path. Both harnesses adopt it.

  **Every content read goes through that helper, not just untracked files.**
  Claude repeats the same `lstat`-then-open-by-path sequence for explicit context
  files (`claude_review_loop/bundle.py:208,221`), where a swap can still follow a
  symlink or block on a FIFO. Size checks must come from the descriptor's
  `fstat`, not from the earlier `lstat`.
- Record redaction metadata in the Pi result so a scoped clean stays
  inspectable, and document the new field in `pi-review-loop/SKILL.md`.

Note the honest scope of the existing redactor: it detects secret-looking paths
and omits their **contents**. It does not guarantee path-name secrecy — the
diffstat is emitted without `redact_diff` (`claude_review_loop/bundle.py:90`)
and `redact_diff` preserves the `diff --git` header (`redact.py:169`). Widening
that is out of scope here; do not claim it.

Acceptance: a private-key block and a `.env`-shaped secret in the working tree
do not have their **values** appear in the Pi bundle; a repository with a
configured textconv driver does not execute it during Pi bundle construction; a
symlink is skipped with a recorded reason; a **path swapped between check and
read** (regular file replaced by a symlink or FIFO) is refused rather than
followed or blocked on — tested for both untracked files and explicit context
files; a bin executed through a symlink resolves `shared/`; both suites green;
one live Pi review returns a verdict on a real diff.

Test accounting: Pi gains redaction, gitio, symlink, path-swap, and bootstrap
tests; Claude gains untracked and context-file path-swap tests and keeps every
redaction test at its new import path. Retained contracts: Claude still asserts
secret-path omission, decoding replacement, oversized/binary/non-UTF context
rejection, and exact prompt-suffix bytes; Pi still asserts bundle size bounds,
skip records, and empty-worktree refusal.

### Phase 2 — Harden the Pi lock in place

No extraction. Bring each Pi slot up to the semantics Claude already proves,
preserving Pi's pool layout and its default of 3 concurrent slots.

- Add the `fcntl` advisory guard across acquisition, reclaim, ownership, and
  release.
- Add owner tokens, token-checked metadata updates, atomic metadata
  replacement, and unique stale tombstones before cleanup.

Acceptance: the cross-version test runs the **parent-commit** `pi-review-loop`
as the holder against a one-slot pool, then a new-semantics contender — the
contender is rejected while the legacy holder is live, and acquires after the
legacy release. Fabricating tokenless metadata does not satisfy this: legacy
code rewrites metadata directly (`cli.py:149`) and releases without an ownership
check (`lock.py:140`), so only a real legacy process exercises it. Also test
normal three-slot capacity with one legacy holder present, stale-reclaim races,
replacement-owner rejection, and release by a non-owner. Pi's on-disk layout and
`--max-concurrent` default are unchanged; documented in the skill.

Test accounting: all new tests land in the Pi suite; Claude is untouched at
158. Retained contracts, Pi: slot-pool capacity, exit code 3 on contention,
stale-slot reclaim, and metadata visibility for operators.

### Phase 3 — Harden the Pi lifecycle in place

Still no extraction. Each item is a declared behavior change.

- Handle `KeyboardInterrupt` on the Pi path and always write a structured
  result, matching `claude_review_loop/runner.py:193`.
- **Check the process group on natural leader exit, in both harnesses.**
  `_kill_group` currently runs only when `proc.poll()` reports the leader alive
  (`claude runner.py:176-177`, `pi runner.py:149`). A wrapper that emits a
  verdict, forks a surviving descendant, and exits normally is therefore
  reported clean with the descendant still running — the exact orphan class the
  harness exists to prevent. Verify group emptiness before returning any verdict
  on the natural-exit path, and tear down before returning if it is non-empty.

**Malformed-stdout policy — decided, not deferred.** Pi keeps treating
non-protocol output as liveness evidence (`pi_review_loop/runner.py:88`) and
does *not* converge on Claude's stricter rule. Rationale: this is backward compatibility and
conservative handling of *unexpected* output, not a claim about the current
CLI — Pi 0.82.0's JSON mode takes over stdout and routes incidental output to
stderr, so non-protocol stdout should not normally occur. Treating whatever
does appear as liveness cannot mask a hang, because the global review deadline
bounds it and garbage can never yield `CLEAN`. The regression test asserts that a garbage-only stream never
yields `CLEAN` and terminates at the global deadline in a failed state.

Acceptance: SIGINT during a live Pi review leaves a structured result and no
orphan; a wrapper that emits `CLEAN`, forks a descendant, and exits normally
results in group teardown and no clean verdict until teardown is confirmed —
tested on both harnesses; the garbage-only stream test passes; both suites
green.

Test accounting: Pi gains interrupt, descendant, and garbage-stream tests;
Claude gains the descendant test. Retained contracts, both suites: stall
detection, global-deadline termination, provider-error mapping, and
always-written artifacts on every exit path.

### Phase 4 — Pi trust boundary

A prompt-semantics change, so instruction and marker land together.

- Add the untrusted repository-evidence rule to the Pi system instruction
  (`pi_review_loop/cli.py:16`) **and** the boundary marker to the Pi bundle in
  the same commit. A heading without the instruction establishes nothing.
- Test forged headings in repository content.

Acceptance: a forged boundary heading inside repository data does not gain
trusted status; one live Pi review returns a usable verdict with the new
instruction; `pi-review-loop/SKILL.md` documents the trust model.

Test accounting: Pi gains forged-heading and instruction-content tests;
Claude is untouched at its Phase 3 count. Retained contracts, Pi: verdict
extraction from the final assistant message, `INVALID` on a missing verdict,
and model-policy rejection of every non-approved model.

### Gate — Reassess before any extraction

Stop here and evaluate. Produce a behavior contract matrix for **every proposed
extraction target** — `lock`, `runner`, `bundle`, `result`, and `monitor` —
naming for each: the behaviors both harnesses must share, the behaviors that
legitimately differ, and which side is authoritative.

The gate's output is a **decision record**, reviewed on its own: the matrix, an
explicit extract-or-stop conclusion per module, the rationale, and the approval.
A successor plan that is not backed by an approved decision record does not
proceed. Known divergences the matrix must resolve, all verified in review:

- Bundle: Pi permits an over-cap mandatory diffstat and keeps its skip manifest
  outside the droppable list (`pi bundle.py:125`); Claude makes skips droppable
  and fails when mandatory content alone exceeds the cap (`claude bundle.py:193,260`).
  Pi exposes `has_changes`; Claude does not.
- Result: Pi emits `raw_verdict_line`; Claude emits `redactions`, `effort`,
  `structured_output`, and tool-use fields.
- Runner: error precedence, stdin/cwd handling, result extraction, and crash
  diagnostics all differ.
- Monitor: Claude's inspection-tool scope policy lives inside `monitor.py`
  (`INSPECTION_TOOLS`, Read/Grep/Glob target canonicalization) and is
  Claude-specific.

A successor plan may propose extraction only against that matrix, decomposed as
adapter protocol, stream pump, process supervisor, and timing state machine —
four commits, not one phase. If the matrix shows the shared surface is thin,
the correct outcome is to stop with Phases 0–4 and keep two harnesses that are
both hardened.

## Verification gates

- Every phase: `just check` green, plus the phase's own acceptance.
- Phases 1, 3, 4: one live Pi review against a real diff. Unit tests against
  fakes have twice missed transport-level bugs here — the `pi --list-models`
  output shape and a bundle with no reviewer instruction.
- **Review gate:** implement in a separate worktree and review each phase using
  harness executables from the **parent commit**, not the modified worktree.
  Phases 1–4 change the Pi harness, so Pi cannot review its own change; use
  `claude-review-loop` from the unmodified canonical checkout.
- **Cutover procedure**, using the Phase 0 barrier because a check-then-switch
  sequence would otherwise race: both CLIs build their bundles *before*
  acquiring a lock (`pi cli.py:97` vs `149`; `claude cli.py:212` vs `243`), so
  lock state alone does not tell you the checkout is idle. Create the barrier
  file, wait for both lock namespaces to drain, `git checkout`, remove the
  barrier. New invocations refuse to start while the barrier exists.

  Residual window, stated rather than hidden: a process that begins importing
  modules in the instant before `git checkout` starts can still load a mixed
  tree, because the barrier is checked in `main()` after imports complete. The
  barrier plus lock drain reduces the exposure to that interval; it does not
  eliminate it. Do the cutover when no session is actively reviewing.

## Risks

- **A concurrent session may be running a review while a phase lands.** These
  harnesses are in active use across repositories, and the canonical absolute
  path is what every skill invokes. Worktree implementation plus a drained
  switch is the mitigation.
- **Symlinked deployment.** `shared/` is reached only through the absolute-path
  invocation the skills already document. Proven by test in Phase 1.
- **Silent coverage loss** while moving tests. The contract matrix, not the
  test count, is the invariant.
- **Phase 2 lock migration.** A holder acquired under old semantics may still
  exist when new-semantics code starts. Tested explicitly before the phase
  lands.
- **The gate may conclude "do not extract."** That is a successful outcome, not
  a failed plan.

## Answered in round 1 review

1. Shared code at repository-root `shared/review_harness/`, not inside one
   skill.
2. The Pi trust boundary lands, but only together with the system instruction,
   as an explicit security behavior change (Phase 4).
3. Keep the `opus-review-loop` shim. Repository-internal callers are migrated,
   but external absolute-path callers cannot be ruled out, and the shim is tiny
   and already documented as uninstalled.
