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

with `CLAUDE_CONFIG_DIR` set to the account's config dir. In print mode
Claude Code runs `/usage` as a local command: no model call, no cost, no
dialog, no saved session (the JSON says `"local_command": "usage"`,
`"num_turns": 0`). It runs in the system temp directory, so no project
settings apply. The `result` text holds the dialog's lines:

```text
Current week (all models): 3% used · resets Nov 12 at 7:59pm (Europe/Berlin)
```

The tool parses the `Current …: N% used · resets …` lines (the year is
inferred, the reset time is converted to UTC) and prints one line:

```sh
tools/claude-usage-read/bin/claude-usage-read                      # $CLAUDE_CONFIG_DIR, else ~/.claude
tools/claude-usage-read/bin/claude-usage-read ~/.claude-katharina  # explicit config dir
# used=4 resets_at=2026-11-12T18:59:00Z observed_at=2026-11-06T15:05:13Z config_dir=/Users/me/.claude-katharina

tools/claude-usage-read/bin/claude-usage-read --json               # all parsed windows
tools/claude-usage-read/bin/claude-usage-read ~/.claude-katharina --report --pool claude-katharina
```

`--report` then runs

```sh
work usage report --provider claude [--pool P] --window "Weekly · all models" \
  --used N --resets-at ISO --observed-at now --source claude-usage-read
```

and passes the `work` output through. `--pool` only applies with `--report`.

| Exit | Meaning |
|------|---------|
| 0 | read (and reported, with `--report`) |
| 1 | could not read or parse the usage (claude missing, failed, timed out, no subscription windows, unknown format); nothing is reported |
| 2 | bad arguments |
| 4 | read, but `work usage report` failed or `work` was not found |

Only the parsed windows are printed. The raw `claude` output, which also
carries account metadata such as the credential expiry, is never echoed, and
`claude`'s stderr is discarded. No tokens or credentials are read by the tool
itself; `claude` uses its own login.

| Variable | Effect |
|----------|--------|
| `CLAUDE_CONFIG_DIR` | Config dir when none is given as argument (default `~/.claude`) |
| `CLAUDE_USAGE_READ_CLAUDE` | `claude` executable to run (default `claude` on PATH) |
| `CLAUDE_USAGE_READ_WORK` | `work` executable for `--report` (default `work` on PATH) |

Limits: the text format is Claude Code's, not a documented API (verified with
Claude Code 2.1.318). A format change makes the tool exit 1 with
"no 'Current ...: N% used' line" instead of reporting a wrong number. The
reading is the server's value for that account, so it covers all machines.

Tests (fixtures with the real output shape; fake `claude` and `work`):
`cd tools/claude-usage-read && python3.14 -m unittest discover -s tests -t .`
