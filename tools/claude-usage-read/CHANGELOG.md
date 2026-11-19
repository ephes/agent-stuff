# claude-usage-read changelog

## Unreleased

- Windows missing: when `/usage` prints only "What's contributing to your
  usage?" (its `/api/oauth/usage` fetch failed, e.g. HTTP 429 for a login with
  many parallel sessions), the error now names the reason from claude's
  `--debug-file` log (rate-limited with the retry delay, login lacks usage
  scope / revoked with the re-login command, or fetch failed), instead of
  "not a subscription login, or the output format changed". The tool then
  falls back to Claude Code's cached reading (`cachedUsageUtilization` in
  `.claude.json`), prints it with `stale=cached` and its real fetch time as
  `observed_at`, reports it (source `claude-usage-read:cache`) only when newer
  than the last cached reading sent for that login, profile, pool and account, and exits 3. A cache from another
  account or from before the weekly reset is not used.

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
