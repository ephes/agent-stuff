# pane-watchdog changelog

## Unreleased

- New tool: read-only scan of herdr panes on the given machines
  (`pane list`, `pane read --format ansi` only; never sends keys). Reports an
  open `/usage` dialog, trust dialog or permission prompt, a finished turn
  whose last message asks a question, and typed (non-dim) text in the `❯`
  input line of panes that run an agent, one tab-separated line per finding. Dim prompt suggestions
  (ghost text) are ignored. Exit 0 none, 1 findings, 2 scan error.
