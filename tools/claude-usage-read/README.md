# claude-usage-read

Reads a Claude account's weekly usage (percent used, reset time) without
opening the interactive `/usage` dialog in a working pane. Python 3 stdlib
only.

Opening `/usage` in an agent pane and closing it with Escape blocked a worker
pane for almost two hours on 2026-11-05: herdr showed it as `idle`, and nobody
noticed the dialog was still open. This tool runs instead:

```sh
claude -p /usage --output-format json --no-session-persistence
```

for the account's config dir. In print mode Claude Code runs `/usage` as a
local command: no model call, no cost, no dialog, no saved session (the JSON
says `"local_command": "usage"`, `"num_turns": 0`). It runs in the system temp
directory, so no project settings apply. The `result` text holds the dialog's
lines:

```text
Current week (all models): 3% used · resets Nov 12 at 7:59pm (Europe/Berlin)
Current week (Fable): 0% used · resets Nov 12 at 8pm (Europe/Berlin)
```

The default dir `~/.claude` is read with `CLAUDE_CONFIG_DIR` **unset**; any
other dir is passed as `CLAUDE_CONFIG_DIR`. Claude Code keeps the default
dir's login in the keychain item `Claude Code-credentials`, but an explicit
`CLAUDE_CONFIG_DIR` (even `~/.claude`) makes it look for
`Claude Code-credentials-<hash>`. Without a login there it prints the
API-cost summary (`Estimated cost: $0.0000 …`) instead of the usage lines,
which is why reading the main account failed before. The child environment
also drops inherited `ANTHROPIC_*`, `CLAUDE_CODE_*`, `CLAUDECODE` and `HERDR_*`
variables: an API key or OAuth token would replace the config dir's login,
and a herdr pane id would tie the read to the caller's pane.

The tool parses the `Current …: N% used · resets …` lines (the year is
inferred, the reset time is converted to UTC) and prints one line for the
weekly all-models window:

```sh
tools/claude-usage-read/bin/claude-usage-read                      # $CLAUDE_CONFIG_DIR, else ~/.claude
tools/claude-usage-read/bin/claude-usage-read ~/.claude-katharina  # explicit config dir
# used=4 resets_at=2026-11-12T18:59:00Z observed_at=2026-11-06T15:05:13Z config_dir=/Users/me/.claude-katharina

tools/claude-usage-read/bin/claude-usage-read --json               # all parsed windows
tools/claude-usage-read/bin/claude-usage-read ~/.claude-katharina --report --pool claude-katharina
```

`--report` then sends every weekly window that has a reset time to
`work usage report --json -` (stdin), one entry per window with
`provider: claude`, `source: claude-usage-read` and the read time as
`observed_at`: `week (all models)` as "Weekly · all models", `week (Fable)` as
"Weekly · Fable", and so on. A per-model line without its own reset time
(unused this week) gets the all-models reset, the account's weekly cycle. The
session window is not reported. It passes
the `work` output through. `--pool P` (e.g. `claude`, `claude-katharina`) and
`--account A` are added to every entry and only apply with `--report`.

On the Studio, the chezmoi-managed LaunchAgent `de.wersdoerfer.usage-collect`
runs this every 15 minutes for `~/.claude` (pool `claude`) and
`~/.claude-katharina` (pool `claude-katharina`), plus
`work usage collect-codex` (see the dotfiles README, "Usage collector").

| Exit | Meaning |
|------|---------|
| 0 | read (and reported, with `--report`) |
| 1 | could not read or parse the usage (claude missing, failed, timed out, no subscription login for that dir, no subscription windows, unknown format); nothing is reported |
| 2 | bad arguments |
| 4 | read, but `work usage report` failed, took longer than 60 s, or `work` was not found |

Only the parsed windows are printed. The raw `claude` output, which also
carries account metadata such as the credential expiry, is never echoed, and
`claude`'s stderr is discarded. No tokens or credentials are read by the tool
itself; `claude` uses its own login.

| Variable | Effect |
|----------|--------|
| `CLAUDE_CONFIG_DIR` | Config dir when none is given as argument (default `~/.claude`); never passed on for `~/.claude` itself |
| `CLAUDE_USAGE_READ_CLAUDE` | `claude` executable to run (default `claude` on PATH) |
| `CLAUDE_USAGE_READ_WORK` | `work` executable for `--report` (default `work` on PATH) |

Limits: the text format is Claude Code's, not a documented API (verified with
Claude Code 2.1.318 and 2.1.326). A format change makes the tool exit 1 with
"no 'Current ...: N% used' line" instead of reporting a wrong number. The
reading is the server's value for that account, so it covers all machines.

Tests (fixtures with the real output shape; fake `claude` and `work`):
`cd tools/claude-usage-read && python3.14 -m unittest discover -s tests -t .`
