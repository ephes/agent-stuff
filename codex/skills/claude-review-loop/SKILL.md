---
name: claude-review-loop
description: Run a progress-driven, fail-closed Claude Code review gate over the current git worktree with a configurable Claude model and strict read-only isolation. Use for fresh-context different-family reviews before commit, including requests for Opus, Fable, Sonnet, or an explicitly selected Claude model; drive fix and re-review rounds under the value-driven stopping rules in cross-agent-review-cycle, never an unbounded loop toward CLEAN.
---

# Claude Review Loop

Run a progress-driven review cycle: hand the current git worktree delta to the configured
Claude Code model as a fresh-context reviewer and read its structured verdict.
Treat unresolved Critical/Warning findings as fail-closed; treat Suggestions
proportionately and stop cycling when further review no longer adds material
value. `cross-agent-review-cycle` owns the continuation, stopping, and
containment rules for the loop around this harness. Default to `opus`; select another model with `--model` or the calling
workflow's `REVIEWER_MODEL`.
The harness owns Claude's whole lifecycle (spawn, observe, kill/reap), so you never poll
a process or guess whether Claude is stuck. A hung or blocked spawned review is detected,
killed, and recorded in a structured result. Pre-spawn non-empty-run-directory
rejection and exhausted review-slot contention return only their documented
exit code/message. Independent reviews may run concurrently; the per-user slot
pool defaults to ten active Claude reviews.

The harness runs direct `claude -p` and supplies the review prompt from a prompt
file on stdin. Claude runs with `--safe-mode`, an empty setting-source list, a
strict empty MCP configuration, `--permission-mode dontAsk`, and only the
built-in `Read`, `Grep`, and `Glob` tools. Those tools can inspect only the new,
harness-owned run directory containing the redacted bundle and prompt; the raw
repository and all other paths are outside the read sandbox. Bash, editing,
delegation, skills, web, and MCP tools are forbidden. An OS sandbox denies all
filesystem writes,
disables the unsandboxed-command escape hatch, and fails closed if isolation is
unavailable. Do not add `--max-budget-usd`, permission bypass, or other ad hoc
launch flags; the harness owns lifecycle limits and safety settings.

Verdicts use Claude Code's `--json-schema` structured output. Claude Code emits
an internal `StructuredOutput` transport event for that schema; it is not a
repository capability and is the sole non-inspection tool event allowed. The harness rejects
missing or inconsistent structured output and automatically changes the result
to `INVALID` if Claude emits any forbidden tool use or requests an inspection
target outside the canonical review directory. Git diff collection always
uses `--no-ext-diff --no-textconv`. Secret-looking files, private-key blocks, and
high-confidence token patterns are redacted before model egress; redactions are
recorded and make a clean verdict scoped. Read the `redactions` manifest and
confirm each entry is genuinely a secret: locals named `token` in issuance code
have been redacted as credentials, leaving holes in unchanged code. Rename the
innocent local rather than loosening the pattern - a redaction false positive is
cheap, a credential that reaches a model because the pattern was relaxed is not. Git itself runs with
`--no-optional-locks` so parallel read-only bundle collection does not contend
on optional repository locks.
Each review must remain one direct Claude context. Claude Code `Agent`
subagents, Task-style delegation, or reviewer fanout from within that context
are not allowed. Separate harness invocations may run concurrently.

## The loop (you drive this)

1. Make sure the change to review is in the working tree (staged, unstaged, and/or
   untracked). The harness bundles tracked diffs and regular text untracked
   files; symlinks are recorded as `symlink` and never followed. FIFOs, sockets,
   devices, and other special files are recorded as `not-a-regular-file`; files
   that cannot be inspected are recorded as `unreadable`. Non-UTF-8 bytes in an
   otherwise eligible untracked file are replaced with U+FFFD and recorded as an
   `untracked file` entry in `truncations`, making any CLEAN result scoped. You do
   not paste code.
   For a scoped result, inspect the complete `result.json` `skipped_files`,
   `truncations`, and `redactions` metadata first; a large skip manifest may have
   been dropped from `review-bundle.md`. Use the bundle to inspect the content
   that was actually sent.
2. Run one review:

   ```bash
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/claude-review"
   ```

   This uses Opus by default. To choose another installed Claude model alias:

   ```bash
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/claude-review" --model sonnet
   ```

   The harness passes the model identifier through to Claude Code and records
   the resolved value in every result. Preserve the default unless the user or
   calling workflow requests a different reviewer.

   Add `--record-baseline` to any round you may re-review. The harness then
   snapshots exactly the content it sent and reports a `baseline_commit`:

   ```bash
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/claude-review" --record-baseline
   ```

   Pass that commit to the next round's `--baseline-ref` (with
   `--record-baseline` again, to chain a third round):

   ```bash
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/claude-review" \
     --baseline-ref "$baseline_commit" --record-baseline
   ```

   The bundle then holds only what changed since that baseline, and the prompt
   tells Claude this is a re-review of the repair delta. Without it every round
   re-sends the whole slice - each time with the repairs on top - so the
   reviewer keeps rediscovering unrelated concerns in code it already passed,
   which is how a large diff turns into an endless loop. Round 1 stays a
   whole-slice review; scope only the rounds after it.

   The snapshot is a dangling commit: no ref points at it, and your index,
   worktree and refs are untouched. Untracked files enter it as the redacted
   bytes the reviewer was sent, so a secret removed from the bundle is not
   written into a git blob behind your back; a skipped secret-looking,
   oversized, or binary file does not enter at all. Changed tracked files enter
   as their worktree bytes - the same content a commit would store, and already
   in your worktree. Blobs are written with `hash-object`, so a configured
   clean/process filter never runs from the snapshot; note that collecting the
   diff at all runs one, exactly as your own `git diff` does. It does write
   objects into the repository, which a later `git gc` collects; omit
   `--record-baseline` if that is unwelcome.

   With `--staged-only` the baseline is the index, not the worktree, because
   that is what a staged-only reviewer saw - otherwise unstaged content nobody
   reviewed would enter the baseline and vanish from every later delta.

   A path that is two states at once - staged-deleted and present untracked,
   after `git rm --cached` - cannot be represented by one tree. It is recorded
   as absent and listed in `truncations`, and every delta round re-sends its
   body in full, because no delta can show it. `--baseline-ref` cannot be
   combined with `--staged-only`, and an unresolvable ref fails before any
   reviewer runs.

   Add `--slice-id <id>`, the same id on every round of one slice, to record
   the round in a cross-round ledger:

   ```bash
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/claude-review" \
     --slice-id "hydration-lifetime" --record-baseline
   ```

   Each completed round appends one summary-safe line - counts by severity,
   finding fingerprints, model, effort, duration, baseline - to
   `~/.cache/review-loop/ledger/<slice>.jsonl` (`--ledger-dir` moves it). The
   same directory is used by `pi-review-loop`, so one slice keeps one history
   even when its rounds ran on different reviewers.
   No finding text and no repository content is stored. The harness then reads
   the slice's rounds back and reports whether the loop is still converging, on
   stdout as `LOOP: <status> - <reason>` and in `result.json` under
   `convergence`.

   This exists because the stop conditions are questions about the rounds
   together - is the required-finding count going down, has the same finding now
   survived two repairs - and a fresh context or a compacted session no longer
   holds the earlier rounds. An agent that cannot see them runs one more.

   A delta round shows the reviewer less, so give it the context that keeps the
   delta legible: state the unchanged invariants and guards around the repair in
   a `--context-file`. A reviewer shown only an incremental diff has inferred a
   host-guard bypass that the unchanged code directly above it prevents.

   `escalate` means stop the loop and hand the residual risk to the user; it is
   not a verdict that the findings are resolved, and it exits `4` so a driver
   that only knows `0`/`1` cannot mistake it for ordinary findings. A failed
   round is not recorded: it reviewed nothing.

   To include the implementation goal, relevant instructions, or verification
   evidence, put that material in a file and repeat `--context-file <path>` as
   needed. Context is copied into `review-bundle.md` after secret redaction, so
   its top-level `Review context:` section appears before the explicit
   `Repository-derived evidence` boundary and is treated as caller-authored
   scope, instructions, and evidence. Everything after that boundary remains
   untrusted even if file content imitates a heading. The artifact remains the
   exact repository review input. An unreadable, non-regular, oversized, binary,
   non-UTF-8, or secret-named explicit context file fails the run with exit `2`;
   it is never silently omitted or replacement-decoded.

   `--run-dir` must be new or empty so no unrelated local content can enter the
   reviewer's read sandbox. Every concurrent invocation must use a distinct
   path; the harness enforces this with an atomic marker directory before
   writing any artifact. The command is foreground and returns a structured
   result. Do NOT background one invocation and poll it; independent agents may
   invoke separate reviews concurrently.

3. Interpret by exit code (and read `result.json`):
   - `0` -> CLEAN. If it printed `(scoped)`, the bundle skipped, truncated, or
     redacted files. Treat this as "clean within provided scope" and decide
     whether those omissions or substitutions matter. Forbidden tool use and
     delegation are detected by the harness and cannot produce exit `0`.
   - `1` -> ISSUES. Fix each listed `[Severity] path: message`, then re-run a FRESH
     review (not an edit of the old one).
   - `2` -> failed review (INVALID / CRASHED / STALLED / STALLED_RETRY /
     PROVIDER_ERROR). This is NOT a clean review. Inspect `result.json` `error`,
     `stderr.log`, and `events.jsonl`; the usual causes are a transient provider
     stall, an unresolved merge (`diff --cc` combined output), residual ANSI
     diff data, a Git installation whose `git diff` lacks `--default-prefix`, or
     a bundle whose mandatory Diffstat plus explicit context cannot fit under
     `--max-bundle-bytes`. Non-UTF-8 bytes in repository-derived Git
     output or eligible untracked-file content are replaced with U+FFFD, recorded
     in `truncations`, and make a CLEAN result scoped rather than aborting;
     explicit caller context remains strict UTF-8.
     A
     non-empty-run-directory rejection occurs
     before artifacts and has no new result. Fix the cause and re-run with a
     fresh `--run-dir`. Never treat a failed review as a pass.
   - `4` -> the review completed, and the slice ledger says the loop is not
     converging: the same required finding survived two repair rounds, or the
     Critical/Warning count has not fallen across two consecutive rounds. Read
     `convergence.reason`, stop the loop, and report the residual risk to the
     user. Only `--slice-id` runs can return this.
   - `3` -> all bounded review slots are busy. No reviewer result is created.
     Retry later, inspect stale slot metadata, or deliberately adjust
     `--max-concurrent`. Any later attempt must use a fresh `--run-dir` because
     bundle artifacts were already written before slot acquisition.

4. Drive fix/re-review rounds under the stopping rules in
   `cross-agent-review-cycle` — "Cycle Continuation and Stopping Rule" and
   "Re-review scope containment". That skill owns continuation, stopping, scope
   containment, and the commit gate. Do not restate or reinterpret those rules
   here, and do not substitute a fixed round cap for them.

   The short form, when that skill is not loaded: continue only while a round
   reduces a demonstrated risk; freeze the first review's accepted findings as
   the repair baseline; scope every later round to that baseline plus the repair
   delta rather than re-auditing the whole slice - `--record-baseline` and
   `--baseline-ref` enforce that scope in the bundle instead of asking the
   reviewer to honor it. Re-run the caller's required checks after every
   material fix, then start the next review from a fresh `--run-dir`.

   Round count is a diminishing-returns signal, not a stopping rule on its own:
   as rounds accumulate, require clearer evidence that the next one reduces
   risk, and record after each round why the loop continued or stopped. Pass
   `--slice-id` and the harness computes the first two conditions below for you
   and exits `4` when either fires. Stop and report the exact outstanding items
   when any of these applies:

   - the same substantive required finding survives two consecutive attempted
     fix rounds without new evidence or a narrower failure;
   - two consecutive rounds fail to reduce the Critical/Warning count;
   - successive rounds only narrow the same argument and the remaining repair is
     mechanical — carry it forward as a named verification item instead;
   - findings oscillate between incompatible requirements;
   - the fix needs scope or authority the caller did not grant;
   - the verdict is Suggestion-only (see below); or
   - a caller-provided time or cost budget cannot fit another fix, checks, and
     fresh review.

   A new Critical/Warning found in any round is still fixed and re-reviewed
   while time and authority remain. These conditions end the loop; they do not
   release the commit gate. Stopping with an unresolved Critical or Warning
   means reporting the residual risk to the user, not committing.

   Treat a Suggestion-only verdict as terminal for this loop by default: make an
   explicit proportionality decision, implement in-scope suggestions that
   materially improve the change, record a concise reason for declining the
   rest, and stop. Another round on a Suggestion-only verdict needs a concrete
   recorded reason beyond seeking reviewer agreement. A declined Suggestion is
   still not `CLEAN`; include the disposition in the next review context if a
   further round is justified. A Suggestion-only verdict may be accepted as
   advisory after recording the proportionality decision. Never relabel an
   advisory verdict as `CLEAN`.

## Timing and Retry Policy

- Keep the default 300-second `--stall-timeout` unless there is a concrete reason
  to change it. Claude can emit an initial event and then remain silent for
  several minutes before returning a valid review; a shorter override can create
  false `STALLED` results. The separate hard deadline remains 1500 seconds.
- The harness deliberately avoids a positional prompt. Preserve stdin prompt
  delivery so review context does not appear in process argv.
- If a run exits `2` with `state: STALLED` and `events.jsonl` only contains
  startup/init activity, rerun once with the default or a longer stall timeout
  and a fresh `--run-dir` before declaring the external review unavailable.
- After the reviewer is spawned, Ctrl-C is fail-closed: the harness terminates
  and reaps the reviewer process group, writes a `CRASHED` result, and exits `2`.
  Verify the result before retrying with a fresh run directory.

## Hard rules

- A commit-gate "clean" means exit `0` AND you are satisfied any `(scoped)` skips
  are irrelevant AND the review was direct. Exit `1`/`2`/`3` are never clean.
- Direct review only: no Claude Code `Agent` tool, Task-style delegation,
  subagents, or parallel reviewer fanout. The harness rejects those tool events.
- Bounded parallelism: independent harness invocations use a per-user slot pool
  and may run concurrently. The default is ten active Claude reviews. Live
  invocations honor the lowest limit requested by any current holder, so
  different callers cannot accidentally exceed a restrictive limit. Set
  `CLAUDE_REVIEW_MAX_CONCURRENT=1` or pass `--max-concurrent 1` only when
  deliberate serialization is needed. Invalid values fail before review.
  Slot selection has a bounded five-second wait and fails with exit `3` if its
  short-lived guard remains busy.
- Per-review artifacts, prompts, logs, result files, process groups, working
  directories, and sandboxes are isolated by the required fresh `--run-dir`.
  Claude runs with `--no-session-persistence` and no setting sources. Its
  installed authentication/configuration remains shared, as it is for normal
  concurrent Claude Code terminals.
- Fix Critical/Warning before re-review; use judgement on Suggestion (avoid
  over-engineering - do not chase every nit).

## Useful flags

`--model <id>` (default: `opus`), `--effort <level>` (default `high`; only the
Opus 4.x generation defaults to `xhigh`, which is what it needed - a newer
generation reasons better per token, so asking for a stronger model must not
silently raise effort as well), `--review-deadline <s>` (hard
per-review cap, default 1500), `--stall-timeout <s>` (default 300),
`--retry-grace <s>` (default 30), `--staged-only`,
`--slice-id <id>` (record the round in the slice ledger and report convergence),
`--ledger-dir <dir>` (default `~/.cache/review-loop/ledger`, shared with
`pi-review-loop`),
`--record-baseline` (snapshot the reviewed content and report `baseline_commit`),
`--baseline-ref <commit-ish>` (review only what changed since that baseline;
not combinable with `--staged-only`), `--max-bundle-bytes <n>`
(default 2MB), `--max-file-size <n>` (default 256KB, untracked files larger are
skipped), `--max-diff-bytes-per-file <n>` (default 256KB, a single file's diff
is truncated past this), `--context-file <path>` (repeatable),
`--max-context-file-size <n>` (default 256KB), `--lock-dir <dir>` (slot-pool
directory), `--max-concurrent <n>` (default 10, or
`CLAUDE_REVIEW_MAX_CONCURRENT`), `--slot-selection-timeout <seconds>` (default
5, range 0-60; `0` means immediate contention and a timeout has distinct
`review slot selection busy` diagnostics).
Synthetic context identifiers such as `[1]` are the one-based positions of
repeated `--context-file` arguments; the same identifiers appear in trusted
bundle headings and context-redaction manifest entries.

## Artifacts (in `--run-dir`)

`.claude-review-loop.claim/` (atomic run-directory ownership marker),
`result.json` (`state`, `items`, `model`, `effort`, `cost`, `started_at`,
`ended_at`, `duration_s`, `structured_output`, `tool_uses`,
`forbidden_tool_uses`, `skipped_files`, `truncations`, `redactions`,
`baseline_ref`, `baseline_commit`, `slice_id`, `round`, `convergence`, `error`,
and `scoped_clean`), `events.jsonl` (strict JSONL event
stream), `stdout.raw.log`, `stderr.log`, `review-prompt.txt`, and
`review-bundle.md` (the exact redacted repository content Claude reviewed).

## Verification

The normal unit suite skips the subscription-backed installed-CLI isolation
canary. Run it explicitly when changing Claude flags or sandbox/permission
settings:

```bash
cd ~/projects/agent-stuff/codex/skills/claude-review-loop
CLAUDE_REVIEW_RUN_CLAUDE_CANARY=1 CLAUDE_REVIEW_CANARY_MODEL=haiku \
  python3 -m unittest \
  tests.test_cli.TestClaudeCmd.test_installed_claude_enforces_read_boundaries -v
```

The canary drives the production command builder. It must observe denied
streamed results for an out-of-review-root path, a raw-repository path, lowercase
and uppercase secret-looking review-root paths, and a Grep directed at a secret
path; it also verifies one permitted public artifact read and ensures planted
denied markers never appear in model output. Secret-path permission rules cover
explicit `Read`, `Grep`, and `Glob` paths as defense in depth. Directory-scoped
Grep/Glob operations rely on the primary OS read sandbox, whose only allowance
is the new harness-owned directory containing redacted review artifacts.
