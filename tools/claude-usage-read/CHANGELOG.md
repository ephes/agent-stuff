# claude-usage-read changelog

## Unreleased

- Read the main account: `~/.claude` now runs with `CLAUDE_CONFIG_DIR`
  unset. An explicit `CLAUDE_CONFIG_DIR=~/.claude` made Claude Code look for a
  per-dir keychain login that does not exist, so `/usage` printed the API-cost
  summary and the tool failed with "no 'Current ...: N% used' line". That
  output now gets its own error naming the missing login.
- The child `claude` no longer inherits `ANTHROPIC_*`, `CLAUDE_CODE_*`,
  `CLAUDECODE` or `HERDR_*` variables (another login, endpoint or pane).
- `--report` sends all weekly windows (all models plus per-model ones such as
  "Weekly · Fable") in one `work usage report --json -` call, with the read
  time as `observed_at`; a per-model window without its own reset time gets
  the all-models reset. New `--account`; the `work` call has a 60 s limit.
- New tool: reads a Claude account's weekly usage through
  `claude -p /usage --output-format json` (a local command: no model call, no
  dialog in a working pane), prints `used=… resets_at=… observed_at=…
  config_dir=…` or `--json`, and with `--report [--pool P]` sends the weekly
  all-models window to `work usage report --source claude-usage-read`.
