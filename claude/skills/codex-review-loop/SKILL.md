---
name: codex-review-loop
description: "Use when a change needs a fresh-context review by GPT-6 Sol before committing — runs `gpt-6-sol` at medium (or, on request, high) reasoning through the Codex CLI as a supervised, fail-closed gate over the current git diff. Never falls back to another model, provider, or a self-review: a different model, a reroute, a capacity error, a crash, or a hang is a structured failure, never a verdict. Drives review → fix → re-review under the value-driven stopping rules in cross-agent-review-cycle. Triggers: \"have sol review this\", \"gpt-6-sol review\", \"codex review before commit\", \"run the codex review loop\"."
---

# Codex Review Loop

Run a bounded review cycle: hand the current diff to `gpt-6-sol` through the
Codex CLI as a fresh-context reviewer and read its structured verdict.
`cross-agent-review-cycle` owns the continuation, stopping, scope-containment,
and commit-gate rules for the loop around this harness; an unresolved Critical
or Warning is fail-closed, and a Suggestion-only verdict is advisory, not
`CLEAN`.

The harness owns Codex's whole lifecycle — spawn in its own process group,
observe, kill and reap on a hang — so you never poll a tmux pane or grep a log
for a sentinel. It always returns a structured result in the same shape as
`pi-review-loop` and `claude-review-loop`, and it shares their redacted bundle,
slot pool, and slice ledger rather than copying them.

## When to use

Before committing a change you want reviewed by `gpt-6-sol`. This is the
default reviewer for a Claude-family implementer and the only model the harness
runs. `pi-review-loop` can run the same model through Pi, but it is a different
harness: use it only when the user asks for Pi. Do not substitute Pi, Claude,
another model, or your own verdict when this gate is unavailable — stop and
report the blocked gate.

## The loop (you drive this)

1. Make sure the change is in the working tree (staged, unstaged, untracked).
2. Run one review in the foreground — do not background it and poll:

   ```bash
   python3 ~/projects/agent-stuff/claude/skills/codex-review-loop/bin/codex-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/codex-review" \
     --slice-id "<slice>" --record-baseline
   ```

   Give the reviewer your intent, scope, and verification evidence with
   `--context-file <path>` (repeatable). That text is copied, redacted, into the
   bundle's trusted `Review context:` section, so write it yourself: never paste
   repository text or earlier reviewer output there.

   The reviewer works in a throwaway copy of the repository at the reviewed
   state (see **Boundary**), so it can find callers, read unchanged code, check
   history and run the tests itself. It cannot read anything outside that copy
   and the review root. When it needs a file from elsewhere — the backend rule
   a client in another repository mirrors — pass that file with
   `--evidence-file <path>` (repeatable). It is copied, redacted, into the
   review root under `evidence/` and labelled as untrusted repository data.
   A secret-looking name, a non-regular, binary, non-UTF-8, or oversized
   (`--max-evidence-file-size`, default 512KB) file fails the run before Codex
   starts; nothing is silently dropped.

   For a re-review, pass the previous round's `baseline_commit`:

   ```bash
   python3 ~/projects/agent-stuff/claude/skills/codex-review-loop/bin/codex-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/codex-review" \
     --slice-id "<slice>" --record-baseline --baseline-ref "$baseline_commit"
   ```

   The bundle then holds only the repair delta, the instruction tells the
   reviewer this is a re-review, and the prompt names the previous round's
   tree so `git diff <tree>` in the copy shows the same delta. State the unchanged invariants around the
   repair in a context file: a reviewer shown only a delta infers bypasses that
   the unchanged guard above it prevents.

   For a cumulative review of a commit series, check out the series' tip with
   a clean tree and pass the commit before the series as `--baseline-ref` with
   `--cumulative`; the bundle is then the whole series' diff, framed as one
   change to review rather than a repair delta. Raise `--max-bundle-bytes` if
   the Diffstat reports dropped sections, and read `truncations`.

3. Interpret by exit code (and read `result.json`):
   - `0` → CLEAN. `(scoped)` means files were skipped, truncated, or redacted —
     treat it as clean within that scope and decide whether the gaps matter.
   - `1` → ISSUES. Verify each finding at its source before acting on it.
   - `2` → failed review: `INVALID`, `CRASHED`, `STALLED`, or `PROVIDER_ERROR`,
     refined by `failure_kind` (`model_mismatch`, `model_unproven`,
     `forbidden_tool`, `provider`, `stall`, `deadline`, `crash`, `verdict`,
     `preflight`, `interrupted`, `ledger`). This is never a pass. `ledger`
     means the review ran but its round could not be recorded under
     `--slice-id`; its findings stay in `items`, but a round missing from the
     history cannot close a cycle. An invalid invocation (a rejected `--model`,
     `--cumulative` without a baseline) also writes an `INVALID` result when its
     `--run-dir` is new or empty; a used directory is never written to. Retry once with a fresh
     `--run-dir`; if it fails again, stop and report — do not substitute
     another reviewer.
   - `3` → every review slot is busy (default ten, shared per user with no
     other harness). Ten concurrent reviews is unusual: check the slot
     metadata under `--lock-dir` before waiting, and ask the user rather than
     looping on retries.
   - `4` → the review completed and the slice ledger says the loop is not
     converging. Stop and report the residual risk.

4. Drive further rounds under `cross-agent-review-cycle`, not a round cap.

## What makes a verdict count

A verdict is accepted only when all of these hold; otherwise the result is
`INVALID` with an explanation:

- **The process succeeded.** A reviewer that exits non-zero on its own is
  `CRASHED`, even after a completed turn and a well-formed verdict. Only a run
  the harness itself ended after `turn.completed` (Codex has hung at exit) is
  judged without a clean exit, and only when the process died of a signal the
  harness confirmed delivering (a negative status; the launcher re-raises the
  signal its child died of). Any positive non-zero status - including 143 or
  137 - is one the process chose and is `CRASHED`, even if it raced the kill.
- **The final message is the schema.** Codex runs with `--output-schema`; the
  final message must be exactly `{"verdict", "findings"}` with CLEAN ⇔ no
  findings, and severities Critical/Warning/Suggestion.
- **The model is proven, not assumed.** `codex exec --json` does not say which
  model answered, so the harness reads Codex's own session record
  (`$CODEX_HOME/sessions/.../rollout-*-<thread>.jsonl`). Every turn must name
  `gpt-6-sol` at the effort the run asked for (`--effort`, default `medium`),
  and the record must hold no model-reroute
  entry. A missing record is `model_unproven`, not a pass. The record is copied
  to `session.jsonl` in the run directory.
- **The review stayed one direct context.** Only the tools `exec` (the code-mode
  host through which `gpt-6-sol` runs sandboxed shell commands), `wait`,
  `exec_command`, `write_stdin`, `shell`, and `update_plan` may appear.
  Anything else — a `collaboration.*` call, a subagent record, an unlisted tool
  — is `forbidden_tool`. The session record is checked, not just the event
  stream: during the boundary investigation a subagent spawn appeared in the
  record but not on stdout.

`CODEX_HOME` is pinned for the subprocess (`CODEX_REVIEW_HOME` overrides it
deliberately; an inherited `CODEX_HOME` is ignored), so the account that runs
the review and the record the harness audits are the same.

Nothing can swap the reviewer: the installed `bin/codex-review-loop` runs the
native binary behind the `codex` found on `PATH` and reads no variable that
replaces it. The fake used
by the tests is injected only through `tests/harness_entry.py`.

## Boundary

Demonstrated against Codex 0.158.0 on macOS with `gpt-6-sol` by
`tests/test_canary.py`, which builds a production copy, asks the model to run
commands inside and outside it, and then checks Codex's session record — which
holds every command's output — and the filesystem. The canary drives the
production copy builder, command builder and runner with a canary instruction,
because the review instruction tells a compliant model not to try.

**The repository copy.** Before Codex starts, the harness makes
`<run-dir>/workspace/repo`: a `git clone --shared --no-checkout` of the
repository, checked out at `HEAD` and brought to the reviewed tree (the
worktree with staged, unstaged and untracked changes; the index with
`--staged-only`). The reviewed changes are uncommitted work there, so
`git status` and `git diff HEAD` show them; the history is borrowed read-only
from the source object store through `objects/info/alternates`. It holds every
tracked file, not ignored files (virtual environments, build output, the usual
`.env`), not untracked or locally modified secret-looking paths (listed under
`review_copy.excluded`; a modified tracked one keeps its committed version),
and not submodule contents; Git LFS files stay pointers. Hooks do not run while it is built, and its
`origin` remote is removed. It is a clone, not a worktree, so nothing is
registered in the source repository. Building the reviewed tree writes
unreferenced objects into the source repository, as `--record-baseline` does;
`git gc` collects them. The harness deletes `<run-dir>/workspace` after the
run — on success, failure, timeout, Ctrl-C and SIGTERM (SIGTERM and SIGHUP are
turned into the Ctrl-C path, which kills and reaps Codex first). SIGKILL
cannot be caught; a copy it leaves behind is inside the run directory and
nothing in the source repository refers to it.

The harness does not use `--sandbox`. It selects a named Codex permission
profile with the filesystem entries `:minimal` = read; `/tmp`, `/private/tmp`,
`/private/var/folders` = deny; the toolchain prefixes that exist
(`/opt/homebrew`, `/usr/local`, `/nix`, `/Library/Developer/CommandLineTools`)
= read; the review root = read; the source repository's object store = read;
and `<run-dir>/workspace` (the copy, a scratch `home/` and a scratch `tmp/`) =
write. Network is enabled. The reviewer's commands run with `HOME` and
`TMPDIR` pointed at the scratch `home/` and `tmp/`.

**The reviewer can:**

- read, write, delete and run anything in `<run-dir>/workspace`: grep the
  copy, run `git log`/`git blame`/`git diff`, commit or branch there (it has
  its own refs), install dependencies and run tests (the canary runs `python3`
  and `uv` there);
- read the review root: `review-bundle.md` and any `evidence/` files;
- read the source repository's object store — the history, which the copy
  already shows;
- read what `:minimal` admits on macOS (system locations such as `/usr/bin`,
  `/etc`, `/Library/Preferences`, `/Applications`) and the toolchain prefixes
  above. These hold installed software, not repository or user data, but they
  are not empty;
- reach the network, so it can fetch packages — and could send what it reads
  anywhere. The copy is the user's code; that was decided deliberately;
- in its model context, not through tools: the review instruction, the stdin
  prompt, Codex's own environment note (cwd, shell, date), and the user's
  global `~/.codex/AGENTS.md`, which Codex injects even with
  `--ignore-user-config` and `project_doc_max_bytes=0`. Keep secrets out of that
  file. The repository's own `AGENTS.md` is not injected.

**The reviewer cannot** (each observed as `Operation not permitted`): read the
source worktree itself, including its ignored and untracked files such as
`.env`; write to it or to its `.git`; read anything else in the user's home —
other projects, `~/.ssh`, `~/.codex`, `~/.gitconfig`; read `/tmp`,
`/private/tmp`, or the rest of `$TMPDIR` (`/private/var/folders/...`), even
though the run directory itself may live there.

Nothing the reviewer does reaches the user's worktree: its writes land in the
copy and its scratch space, its commits and refs in the copy's own `.git`, and
the copy has no remote to push to.

**It cannot read the caller's environment.** Codex starts from an allowlist -
`HOME`, `USER`, `LOGNAME`, `PATH`, `SHELL`, `TMPDIR`, `TERM`, locale, proxy and
CA-bundle variables, and the pinned `CODEX_HOME` - and its commands run with
`shell_environment_policy.inherit="core"`. The canary plants one marker in the
caller's environment and one in Codex's own, has the model run `env` and
`printenv`, and requires both to be absent from the session record.

**It cannot delegate:** `agents.enabled=false` removes the collaboration tools,
and the account-bound app tools, plugins, browser, computer use, image
generation, and web search are disabled explicitly — `--ignore-user-config`
alone does not remove them. The session-record audit refuses any tool beyond
the shell and plan tools. Starting another `codex` from the shell would find no
credentials: `~/.codex` is unreadable.

The boundary is Codex's enforcement, verified by the canary for this Codex
version. It is not something the harness can re-prove on every run. Re-run the
canary after a Codex upgrade or any change to `command.py` or the copy
builder:

```bash
cd ~/projects/agent-stuff/claude/skills/codex-review-loop
CODEX_REVIEW_RUN_CANARY=1 python3 -m unittest tests.test_canary -v
```

## Lifecycle and timing

- The prompt goes to Codex on stdin; passed as an argument it has silently hung.
- `--stall-timeout` (default 600s) kills a run that neither prints an event nor
  grows its session record. Codex thinks silently for minutes; growth of the
  session record is what keeps a working reviewer alive.
- `--review-deadline` (default 2700s) is the hard cap.
- `--exit-grace` (default 30s): after `turn.completed`, Codex gets this long to
  exit before the harness kills the group and judges the completed turn.
- The harness starts the native Codex binary, not the npm `codex` launcher on
  `PATH`. The launcher installs its own SIGTERM handler, so after its child is
  killed it re-raises the signal into that handler and exits 0 - a killed
  reviewer would read as a clean exit. The native binary's status is the
  operating system's (`-15` for SIGTERM, `-9` for SIGKILL; checked by the live
  `TestLiveSignalAttribution`). A `codex` that is a script whose native binary
  cannot be found is a `preflight` failure, never run through the launcher.
- The harness kills the whole process group and checks that the group is gone,
  not just that its leader exited.
- `unbounded_connection_retries` is disabled so a capacity problem ends as
  `PROVIDER_ERROR` instead of retrying until the deadline.
- Ctrl-C kills and reaps the reviewer and writes a `CRASHED` result.

## Hard rules

- `gpt-6-sol` only. `--model` accepts nothing else.
- Effort `medium` by default; `--effort high` only when the user asked for
  high. Nothing else is accepted, and the run is proven at the effort it
  asked for, so a high run that answered at another effort is `INVALID`.
- A commit-gate "clean" is exit `0` plus your judgement that any `(scoped)`
  omissions do not matter. Exits `1`–`4` are never clean.
- Up to ten concurrent reviews by default (`--max-concurrent`,
  `CODEX_REVIEW_MAX_CONCURRENT`). Live holders honor the lowest limit any of
  them requested, so one run started with `--max-concurrent 1` serializes
  everyone until it ends; lower it only for deliberate serialization.
- Never add `--dangerously-bypass-approvals-and-sandbox`, `--sandbox`, or a
  wider permission profile to get a review through, and never point the
  reviewer at the real worktree instead of its copy.

## Useful flags

`--effort` (`medium` default, or `high`), `--context-file` (repeatable),
`--evidence-file` (repeatable),
`--record-baseline`, `--baseline-ref`, `--cumulative`, `--slice-id`, `--ledger-dir` (default
`~/.cache/review-loop/ledger`, shared with the sibling harnesses),
`--staged-only`, `--max-bundle-bytes` (default 2MB), `--max-file-size`,
`--max-diff-bytes-per-file`, `--max-context-file-size`,
`--max-evidence-file-size`, `--stall-timeout`, `--review-deadline`,
`--exit-grace`, `--lock-dir`, `--max-concurrent`.

## Artifacts (in `--run-dir`)

`result.json` (the siblings' fields — `state`, `items`, `model`, `effort`,
`skipped_files`, `truncations`, `redactions`, `baseline_ref`,
`baseline_commit`, `slice_id`, `round`, `convergence`, `error`,
`scoped_clean` — plus `failure_kind`, `thread_id`, `session_record`,
`observed_models`, `observed_efforts`, `tool_uses`, `forbidden_tool_uses`,
`evidence_files`, `review_copy` — the copy's `head`, `tree`, `excluded`
paths, `notes` and whether it was `removed` — and `structured_output`),
`review-root/` (the bundle and evidence the reviewer started from),
`review-prompt.txt` (stdin), `output-schema.json`,
`last-message.json`, `events.jsonl`, `stdout.raw.log`, `stderr.log`, and
`session.jsonl` (the copied session record).

## Tests

```bash
cd ~/projects/agent-stuff/claude/skills/codex-review-loop
python3 -m unittest discover -s tests
```

`tests/fake_codex.py` receives the production argv and plays each failure: a
wrong model or effort, a reroute, a missing record, delegation in the record or
the stream, an unlisted tool, capacity, an error exit, a crash, a non-zero exit
after a completed turn, a silent hang, a busy hang past the deadline, a
post-turn hang, an orphaned child, and malformed final messages. It records the
environment it was given, so the allowlist is tested too, and what it found in
its working directory before writing into it, so the tests prove the copy is
the reviewed state, that its writes never reach the source worktree, and that it
is removed after a clean run, a killed run and a SIGTERM to the harness. The fake refuses to
run against the real `~/.codex`, and it reaches the CLI only through
`tests/harness_entry.py`.
