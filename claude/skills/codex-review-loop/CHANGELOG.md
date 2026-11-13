# codex-review-loop changelog

## Unreleased

- A Codex that macOS Gatekeeper holds at its first launch no longer stalls a
  review for ten minutes without a word. On 2026-11-13 Homebrew's `codex`
  cask installed Codex 0.168.0 with the `com.apple.quarantine` attribute; its
  first launch waited on a Gatekeeper dialog on the screen of a headless Mac,
  so two reviews printed nothing, wrote no session record and ended `STALLED`
  with an empty `error` - while `codex exec` worked once someone had confirmed
  the dialog. The CLI flags and event stream were unchanged in 0.168.0.
  - Before the repository copy is made, the native binary's quarantine
    attribute is read; a binary that is quarantined and was never approved is
    refused as `CRASHED` / `preflight` without starting Codex, and `error`
    says how to approve it or clear the attribute.
  - New `--startup-timeout` (default 120s): a Codex that has not reported
    `thread.started` that long after its launch is killed as `STALLED` /
    `stall`, independent of `--stall-timeout`.
  - Every stall and deadline result now carries a one-line `error` (which
    timeout ended the run, and for a run that never started a thread, the
    Gatekeeper hint), printed after `failure:` on the terminal.
