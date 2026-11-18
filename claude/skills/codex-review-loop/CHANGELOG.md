# codex-review-loop changelog

## Unreleased

- The review model is now `gpt-6.2-sol` (was `gpt-6.1-sol`), still at `high`
  by default and `medium` on request, with the same fail-closed pin: any other
  model, a reroute or a different effort in the session record is
  `model_mismatch`. New GPT-6.2 floor (owner rule 2026-11-18): `--model` with
  an id below 6.2 (`gpt-6.1-sol`, `gpt-6-sol`, ...) is refused as `INVALID`
  before anything runs with "older than GPT-6.2", `codex_cmd` and `model_for`
  raise for such an id, and an audit that finds a turn on one names it as
  below the floor. `gpt-6.2-astra` is not a review model and is refused like
  any other id.
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
