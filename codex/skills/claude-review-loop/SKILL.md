---
name: claude-review-loop
description: Run a progress-driven, fail-closed Claude Code review gate over the current git worktree with a configurable Claude model, working in a sandboxed throwaway copy of the repository. Use for fresh-context different-family reviews before commit, including requests for Opus, Fable, Sonnet, or an explicitly selected Claude model; drive fix and re-review rounds under the value-driven stopping rules in cross-agent-review-cycle, never an unbounded loop toward CLEAN.
---

# Claude Review Loop

Run a progress-driven review cycle: hand the current git worktree delta to the configured
Claude Code model as a fresh-context reviewer and read its structured verdict.
Treat unresolved Critical/Warning findings as fail-closed; treat Suggestions
proportionately and stop cycling when further review no longer adds material
value. `cross-agent-review-cycle` owns the continuation, stopping, and
containment rules for the loop around this harness. Default to `claude-opus-5-5` (Opus 5.5) at `medium` effort; select another model with `--model` or the calling
workflow's `REVIEWER_MODEL`.
The harness owns Claude's whole lifecycle (spawn, observe, kill/reap), so you never poll
a process or guess whether Claude is stuck. A hung or blocked spawned review is detected,
killed, and recorded in a structured result. Pre-spawn non-empty-run-directory
rejection and exhausted review-slot contention return only their documented
exit code/message. Independent reviews may run concurrently; the per-user slot
pool defaults to ten active Claude reviews. Baseline snapshots require Git 2.25
or newer because they use the NUL-delimited `--pathspec-from-file` interface.

The harness runs direct `claude -p` and supplies the review prompt from a prompt
file on stdin. Claude runs with `--safe-mode`, an empty setting-source list, a
strict empty MCP configuration, `--permission-mode dontAsk`, and only the
built-in `Read`, `Grep`, `Glob`, `Bash`, `Edit`, and `Write` tools, in a
throwaway copy of the repository at the reviewed state (see **Repository copy
and boundary**). It can read, search, run git and tests, and write there; it
cannot reach the source worktree or the rest of the home directory. Delegation
(`Agent`/`Task`), skills, web, notebook, background-monitor, and MCP tools are
forbidden. Do not add `--max-budget-usd`, permission bypass, or other ad hoc
launch flags; the harness owns lifecycle limits and safety settings.

## Repository copy and boundary

Before Claude starts, the harness makes `<run-dir>/workspace/repo`: a
`git clone --shared --no-checkout` of the repository, checked out at `HEAD` and
brought to the reviewed tree (the worktree with staged, unstaged and untracked
changes; the index with `--staged-only`). The reviewed changes are uncommitted
work there, so `git status` and `git diff HEAD` show them, and the history is
borrowed read-only from the source object store through
`objects/info/alternates`. The copy holds every tracked file, not ignored files
(virtual environments, build output, the usual `.env`), not untracked or locally
modified secret-looking paths (listed under `review_copy.excluded`; a modified
tracked one keeps its committed version), and not submodule contents; Git LFS files stay pointers. Hooks do
not run while it is built, and its `origin` remote is removed, so a `git push`
there has nowhere to go. It is a clone, not a worktree, so nothing is registered
in the source repository; `git worktree list` never shows it. Building the
reviewed tree writes unreferenced objects into the source repository, as
`--record-baseline` does; `git gc` collects them. The same shared module builds
the copy for `codex-review-loop` and `pi-review-loop`.

The harness deletes `<run-dir>/workspace` after the run - on success, failure,
timeout, Ctrl-C and SIGTERM (SIGTERM and SIGHUP take the Ctrl-C path, which
kills and reaps Claude first). SIGKILL cannot be caught; a copy it leaves
behind is inside the run directory.

Before deleting it, the harness gives the owner access to every directory
inside it again, so a reviewer that left a directory with mode 000 behind does
not keep it alive. That walk works through directory descriptors, one path
component at a time: it never follows a symbolic link and skips a directory
that changed under it, so even a process the reviewer left running cannot steer
it outside the copy. A copy that still cannot be deleted is reported on stderr
and as `review_copy.removed: false` in `result.json`; the verdict and the slice
ledger round are recorded either way.

What confines the reviewer, verified by the canary under **Verification**:

- **Bash** runs in Claude Code's OS sandbox (`failIfUnavailable`, no unsandboxed
  retry, `autoAllowBashIfSandboxed`). Reads are denied for the user's home,
  `/private/var/folders` (the per-user `TMPDIR`), every entry of `/private/tmp`
  present at launch, and every entry of Claude's own temporary directory
  `/private/tmp/claude-<uid>` present at launch - the other Claude sessions'
  scratch space - and re-opened for `<run-dir>/workspace` and the source object
  store. Writes are allowed in `<run-dir>/workspace` and, because Claude's Bash
  tool keeps its working-directory state there and cannot run without it, in
  Claude's own temporary directory, except the entries present at launch that
  do not hold the workspace. Network is open (`allowedDomains: ["*"]`), so a
  test run can fetch dependencies. System and toolchain paths such as `/usr`
  and `/opt/homebrew` stay readable, so git, `python3` and `uv` run. Claude's
  sandbox also refuses some writes inside `.git`, even in the copy (observed:
  `git init` copying hook templates into `.git/hooks`).
- The reviewer's process gets `GIT_CONFIG_GLOBAL` and the XDG configuration,
  cache, data and state directories pointed into `<run-dir>/workspace/home`:
  the real home is unreadable, and git refuses to run when it cannot read its
  global configuration. `HOME` itself stays, because Claude needs its
  credentials.
- **Read, Grep, Glob, Edit, Write** are not sandboxed by Claude; `dontAsk`
  permission rules allow `Read` and `Edit` (which also governs `Write`) only
  under `<run-dir>/workspace`, so a call outside is refused. The harness also
  checks every file-tool target itself (see below).

What is **not** closed: a directory created under `/private/tmp` or Claude's
temporary directory after launch is not in the deny lists; the reviewer can
create new files in Claude's temporary directory; and the network is open, so
anything the reviewer reads could leave the machine. The copy is the user's
code and was deliberately made readable; the bundle stays redacted.

Verdicts use Claude Code's `--json-schema` structured output. Claude Code emits
an internal `StructuredOutput` transport event for that schema; it is not a
repository capability and the only allowed tool beyond the six above. The harness rejects
missing or inconsistent structured output and automatically changes the result
to `INVALID` if Claude emits any forbidden tool use. A `Read`, `Grep`, `Glob`,
`Edit` or `Write` call that targets something outside `<run-dir>/workspace` is
held until Claude
answers it: when the answer is exactly Claude's `dontAsk` permission-denial
text for that tool (one text result, nothing else), no data came back, so the call is recorded in `denied_tool_uses`, the summary prints a
`denied:` line, and the review continues. Any other answer (data, a
non-permission error, a reworded denial) or a verdict that arrives before the answer turns the
result `INVALID`. The review instruction names the working directory and asks
for relative paths, so such calls should be rare. `Bash` targets are not
checked by the monitor - a command line has no reliable target - and rely on
the OS sandbox. Git diff collection always
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

   This uses Opus 5.5 (`claude-opus-5-5`) at `medium` effort by default. To
   choose another installed Claude model id or alias:

   ```bash
   python3 ~/projects/agent-stuff/codex/skills/claude-review-loop/bin/claude-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/claude-review" --model sonnet
   ```

   The harness passes the model identifier through to Claude Code and records
   the resolved value in every result. Preserve the default unless the user or
   calling workflow requests a different reviewer.

   Add `--record-baseline` to any round you may re-review. The harness then
   snapshots the reviewed worktree state, subject to the explicit omissions
   reported below, and reports a `baseline_commit`:

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
   worktree and refs are untouched. It holds included worktree content as Git
   would store it. Secret-looking untracked paths and every other refused
   untracked path still do not enter at all. When a file's contents were
   redacted in the bundle, however, its raw, unredacted worktree content is
   passed to Git for the local snapshot (subject to any clean filter). `git add`
   may run a configured clean/process filter, just as diff collection already
   does. The dangling snapshot objects stay local and a later `git gc` collects
   them; omit `--record-baseline` if writing those temporary objects is
   unwelcome.

   Baseline recording fails closed before the reviewer runs when Git cannot
   read or index an included path; the harness error names the affected path
   and Git's reason. A worktree directory at an included path is excluded and
   recorded in `truncations` unless that exact path is already a gitlink in the
   index, preventing recursive inclusion or an accidental embedded-repository
   gitlink. A gitlink records only the submodule commit, so dirty content inside
   an included submodule is not captured and is reported in `truncations`.

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
   reviewer's workspace. Every concurrent invocation must use a distinct
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

`--model <id>` (default: `claude-opus-5-5`), `--effort <level>` (default
`medium` for Opus 5.5, `high` for every other model including the `opus` alias,
and `xhigh` only for the Opus 4.x generation that needed it - a newer generation
reasons better per token, so asking for a stronger model must not silently
raise effort as well), `--review-deadline <s>` (hard
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
`forbidden_tool_uses`, `denied_tool_uses`, `skipped_files`, `truncations`, `redactions`,
`baseline_ref`, `baseline_commit`, `slice_id`, `round`, `convergence`, `error`,
`review_copy` - the copy's `head`, `tree`, `excluded` paths, `notes`, and
whether it was `removed` - and `scoped_clean`), `events.jsonl` (strict JSONL
event stream), `stdout.raw.log`, `stderr.log`, `review-prompt.txt`, and
`review-bundle.md` (the redacted starting point Claude was given). The copy
itself is gone after the run.

## Verification

The normal unit suite skips the subscription-backed installed-CLI isolation
canary. Run it explicitly when changing Claude flags, sandbox or permission
settings, or the copy builder:

```bash
cd ~/projects/agent-stuff/codex/skills/claude-review-loop
CLAUDE_REVIEW_RUN_CLAUDE_CANARY=1 CLAUDE_REVIEW_CANARY_MODEL=haiku \
  python3 -m unittest \
  tests.test_cli.TestClaudeCmd.test_installed_claude_confines_the_reviewer_to_its_copy -v
```

The canary builds a production copy and drives the production command and
environment with a prompt that asks the model to try every path. Inside the
copy it requires a read, `git log`, a Bash write, a `Write`-tool write, a
network fetch and a `python3` run to work. Outside it requires every attempt -
a file in the home directory, the source worktree's ignored file and `.env`, a
file directly under `/private/tmp`, a Bash write and a `Write`-tool write into
the source worktree, a `Read` of the source worktree - to be recorded and to
return nothing: no planted marker may appear in the output, and neither write
may land. Verified with Claude Code 2.1.284 on macOS.
