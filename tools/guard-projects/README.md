# guard-projects

Two small guards for agent shells. Python 3 stdlib only.

- `bin/guard-projects`: a Claude Code `PreToolUse` hook for the Bash tool. It
  blocks (exit 2, reason on stderr) commands that would write inside
  `~/projects`, which is read-only for agents: `git`
  commit/checkout/switch/stash/pull/reset/merge/rebase/restore/clean and
  similar, `rm`/`mv`/`touch`/`mkdir`/`cp`/`tee`/`sed -i` and `>` redirects onto
  paths there, and build or test tools (`make`, `npm`, `uv`, `cargo`,
  `pytest`, `xcodebuild`, ...) run with a working directory there. It follows
  `cd`, `git -C` and `bash -c`. Reads, `git fetch` and
  `git -C ~/projects/<repo> worktree add ~/workspaces/...` stay allowed. It
  also blocks `git push` to a remote that is not under `github.com/ephes/`.
- `bin/check-push-remote [remote]`: exits 1 unless the remote (default
  `origin`) of the current repository is under `github.com/ephes/`. Use it
  before every push:

  ```sh
  ~/projects/agent-stuff/tools/guard-projects/bin/check-push-remote && git push -u origin HEAD
  ```

`GUARD_PROJECTS_ROOT` and `GUARD_PUSH_OWNER` override `~/projects` and `ephes`
(for tests). The hook is a heuristic seatbelt, not a sandbox: an interpreter
writing files itself is not caught.

## Enabling the hook

Not installed anywhere by default. To enable it for every Claude Code session,
the owner adds this to `~/.claude/settings.json` (via the chezmoi source):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/projects/agent-stuff/tools/guard-projects/bin/guard-projects"
          }
        ]
      }
    ]
  }
}
```

The owner's own terminal is unaffected; only agent Bash tool calls pass through
the hook.

## Tests

```sh
cd tools/guard-projects && python3 -m unittest discover -s tests -t .
```
