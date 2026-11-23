# obs-triage changelog

## Unreleased

- The review runs on Claude instead of Codex: `claude-opus-5-5` (effort
  medium) on the claude-katharina account, as one headless `claude -p` per
  round without tools (`--tools ""`, `--restricted`, `--safe-mode`, no
  settings, hooks, skills, plugins or MCP servers, no saved session, no
  fallback model) and with the schema as `--json-schema`, in a fresh work
  directory with an allowlisted environment and a pinned
  `CLAUDE_CONFIG_DIR=~/.claude-katharina`. An answer from any other model is
  refused. The owner stopped all OpenAI use on 2026-11-21, so the triage had
  been skipped every day since 22.11. (and Nyxmon's "Daily evidence pack and
  triage fresh" stayed critical). The Codex quota guard is gone; a used-up
  Claude limit (HTTP 429) skips the day as "Claude-Kontingent ist
  aufgebraucht (HTTP 429)", other failures with their exit code or HTTP
  status. Input pack, prompt, schema, rounds, ledger writes and the
  Telegram digest are unchanged; the old Codex skip reasons still pass the
  digest check for results waiting in the outbox.
  `OBS_TRIAGE_CODEX_BIN`, `OBS_TRIAGE_QUOTA_GUARD` and `OBS_TRIAGE_CODEX_HOME`
  became `OBS_TRIAGE_CLAUDE_BIN` and `OBS_TRIAGE_CLAUDE_CONFIG_DIR`.

- `launchd-check` skips a plist launchd has not loaded (`launchctl print`
  exit 113, "Could not find service") instead of counting it in `errors`:
  on the Studio five jobs kept unloaded on purpose (opsgate API and runner,
  Daybook photos-offload and voice-memo-attention, the Coreso windows
  publisher) held Nyxmon's "Studio launchd crash loops" check in a
  permanent warning. Other failures and timeouts still count.

- New tool: the daily observability review. Fetches macmini's evidence pack
  over root SSH (an inventory of hosts, services and volumes, raw log samples
  of every service at any level, changes against the baseline), adds the
  Studio's launchd jobs and the ledger's open and recent items, and lets
  Codex (`gpt-6.2-sol`, medium, read-only sandbox without network,
  structured output) review the last 24 hours open-endedly: in up to six
  rounds (150 minutes in all) the model asks for read-only LogQL queries and
  InfluxDB series (by tag selector), which run on macmini (`obs_ctl.py query`) and come back in the
  next round with its own notes, until it names only genuinely new problems.
  They become work items (stage `idea`, campaign `obs-triage`, at most 5 a
  day); the model reports secrets found in logs only as markers
  `[secret:<type> abc…(12)]` (at most four first characters and a quarter of the length; types password, token, secret, api-key, access-key, private-key, key, cookie, session-id, credential, authorization, bearer, basic), a text field naming a credential outside such
  a marker, or with a character outside a closed list (printable ASCII,
  äöü and a few accented letters, common typographic signs; not ß, which
  withholds even ordinary German text), or with a token-like run, is
  withheld (the run report on the Studio keeps it); mail addresses are
  masked before the ledger or Telegram sees them. The digest goes back to macmini and out through Nyxmon's Telegram
  notifier: Telegram is outside the estate, so the digest carries no model
  text, only the item slugs (`obs-<date>-<n>`, assigned by the tool),
  severities (high marked) and fixed
  words (a waiting message whose lines do not all match that grammar is
  replaced by the notice "Nachricht verworfen (nicht im Digest-Format)");
  titles and evidence are in the ledger (best effort: withheld when
  they look like they carry a secret) and the local run report. A quiet day sends no message; a skipped day
  (Codex unavailable, budget used up), an unfinished review (the last round
  still asked for queries), failed ledger writes, or findings beyond the
  daily limit of five (counted, kept in the run report) send a short notice. Raw log text reaches the model provider (owner decision
  2026-11-19). No fallback model: a day Codex cannot run is reported as
  skipped. `launchd-check` reports the Studio's launchd crash loops to
  macmini for Nyxmon every ten minutes; `weekly` starts the Monday review
  worker on the main account. Installed as three chezmoi LaunchAgents on
  the Studio.
