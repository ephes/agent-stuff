# claude-usage-read changelog

## Unreleased

- New tool: reads a Claude account's weekly usage through
  `claude -p /usage --output-format json` (a local command: no model call, no
  dialog in a working pane), prints `used=… resets_at=… observed_at=…
  config_dir=…` or `--json`, and with `--report [--pool P]` sends the weekly
  all-models window to `work usage report --source claude-usage-read`.
