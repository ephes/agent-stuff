# obs-triage changelog

## Unreleased

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
