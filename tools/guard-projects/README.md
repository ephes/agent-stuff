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
  also blocks `git push` unless every URL it would push to is under
  `github.com/ephes/` (see below).
- `bin/check-push-remote [git push arguments]`: exits 1 unless a `git push`
  with the same arguments, run in the current repository, would push only to
  `github.com/ephes/`. Without arguments it checks what a bare `git push`
  would use. Use it before every push:

  ```sh
  ~/projects/agent-stuff/tools/guard-projects/bin/check-push-remote -u origin HEAD && git push -u origin HEAD
  ```

Both resolve the push target the way git does, without contacting any remote:

- options are parsed with their values (`-o ci.skip`, `--push-option`,
  `--receive-pack`, unique abbreviations such as `--rep`), and the first
  positional argument wins over `--repo`;
- a bare `git push` uses `branch.<current>.pushRemote`, then
  `remote.pushDefault`, then `branch.<current>.remote`, then the only remote,
  then `origin`;
- every `git remote get-url --push --all` URL is checked, so a `pushurl` or
  `pushInsteadOf` pointing elsewhere is caught; a repository given as a URL or
  path gets the same `pushInsteadOf`/`insteadOf` rewriting;
- `git -C`, `--git-dir`, `--work-tree`, `-c`/`--config-env` and leading
  `VAR=value` assignments are applied while resolving.

Anything that cannot be resolved (unknown or ambiguous option, missing
repository, no push URL) is refused rather than allowed.

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
