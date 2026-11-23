# obs-triage

The LLM half of the daily observability routine, plus two small Studio jobs
around it. Python 3 stdlib only.

Owner decisions 2026-11-18/19: the daily job looks for problems **nobody
knows about yet**; known problems are fixed through their work items. Its
core is an open-ended review of the last 24 hours of raw logs and metrics
by an LLM that forms its own hypotheses and drills down. macmini builds a
deterministic evidence pack every morning (ops-deploy `services.obs_daily`,
ops-control `docs/OBSERVABILITY_ROUTINE.md`) that helps it navigate without
filtering anything; this tool runs the review with Claude and files what is
new.

Model: `claude-opus-5-5` (effort medium) on the claude-katharina account
(`CLAUDE_CONFIG_DIR=~/.claude-katharina`), since 2026-11-23. Until then the
review ran on Codex (`gpt-6.2-sol`, last run 2026-11-21); the owner stopped all OpenAI use on
2026-11-21 ("bitte nichts mehr über openai laufen lassen ... wenn dann
claude-katharina"), and the triage was skipped every day from 22.11. on.

```sh
tools/obs-triage/bin/obs-triage run              # the daily triage (LaunchAgent, 07:30)
tools/obs-triage/bin/obs-triage run --dry-run    # no work items, no message; prints the digest
tools/obs-triage/bin/obs-triage launchd-check    # launchd crash loops to macmini (every 10 minutes)
tools/obs-triage/bin/obs-triage weekly           # start the weekly review worker (Monday)
```

## `run`

1. Under a run lock, read which items this day already attempted
   (`~/.local/state/obs-triage/days/<date>.json`): reruns count them against
   the daily limit (a write whose acknowledgement was lost may have landed)
   and do not create them again.
2. Fetch today's pack from macmini over root SSH (`obs_ctl.py pack`); a pack
   from another day fails the run.
3. Add the Studio's own launchd jobs that ran or failed since the last daily
   run (`launchd-daily.json`) and the ledger's items: open ones and those
   changed (or dropped) in the last 21 days, as slug, stage, project and title
   only (`work items --json`; an incomplete list fails the run).
4. The review, in rounds (at most `MAX_ROUNDS` = 6, 150 minutes in all, 25
   per round). Each round is ONE headless Claude call without tools:
   `claude -p --model claude-opus-5-5 --effort medium --output-format json
   --no-session-persistence --permission-mode dontAsk --tools "" --restricted
   --safe-mode --disable-slash-commands --setting-sources ""
   --strict-mcp-config --mcp-config '{"mcpServers":{}}' --json-schema
   <triage-schema.json>`: no built-in tools (no commands, files or network),
   no user, project or local settings, hooks, CLAUDE.md, skills, plugins,
   slash commands or MCP servers, no saved session and no `--fallback-model`.
   It starts in a fresh work directory under the state directory (also its
   `CLAUDE_CODE_TMPDIR`, removed after the round) with an allowlisted
   environment (no `ANTHROPIC_*` key, token or base URL, no `CLAUDE_CODE_*`
   overrides) and a pinned `CLAUDE_CONFIG_DIR` (`~/.claude-katharina`, the
   login it uses), the prompt on standard
   input; SIGTERM/SIGINT kill the process group it started. The prompt is
   the brief (`triage-brief.md`), the pack, the launchd jobs and the items
   (the same in every round, first, so the provider can cache it), then the
   rounds so far: the model's `notes` and its queries with their results.
   The model either asks for up to 8 read-only queries (`kind` `loki` for
   LogQL; `influx` or `influx_series` with a tag selector such as
   `metric=host.load5 subject_id=fractal`, from which macmini builds the
   Flux) or gives its final answer. Queries go to macmini in one
   `obs_ctl.py query` call (bounded there: 31-day range, 500 lines or points,
   60 s and 24 KiB per result, read-only token); a refused or failed query
   comes back as an error the model can react to. Results carried into later rounds stay below 600 KiB (older
   rounds' results give way first; the notes stay). The last round, or one
   started without room for queries and a final round of 20 minutes, must
   answer; one budget covers the rounds and the queries,
   and a round is never started with less than a minute left (the day is
   then `skipped`). A last round that still asks for queries is filed but
   reported as `failed` ("Untersuchung nicht abgeschlossen").
   The answer is the result event's `structured_output` and must have the
   schema's shape; the event's `modelUsage` must name `claude-opus-5-5` and
   no other model.
5. Raw log text reaches the model provider, now Anthropic (owner decision
   2026-11-19, recorded as an accepted residual risk in ops-deploy
   `docs/services/obs_daily.md`; the provider changed with the owner's
   2026-11-21 "wenn dann claude-katharina"); the brief asks the model to report secrets
   only as markers `[secret:<type> abc…(12)]` (see 6).
6. Each valid finding becomes a work item `obs-<date>-<n>` (numbered over
   the day's reruns; never taken from model text, because the slug is what
   Telegram shows). The model's slug is a hint for deduplication within the
   day (3 to 41 characters of `[a-z0-9-]`, full match; not a credential word
   or token-like; kept in the day file and the run report only); title
   at most 120 and summary at most 600 characters). Each text field (the
   first 4,000 characters are looked at) is withheld whole, replaced by a
   pointer to the local run report, when
   - it holds a character outside a closed list (printable ASCII, line
     breaks, tabs, äöü and a few accented letters, common typographic
     signs; no ß: `ALLOWED_TEXT`);
   - it names a credential outside a strict marker `[secret:<type> abc…(12)]`
     (at most four first characters and a quarter of the length; types
     password, token, secret, api-key, access-key, private-key, key, cookie,
     session-id, credential, authorization, bearer, basic): the stems of
     `CREDENTIAL_WORDS` (passw, token, secret, cookie, authoriz, bearer,
     apikey, ...) anywhere in the text folded to lower-case letters and
     digits, and the whole words of `CREDENTIAL_SHORT_WORDS` (key, keys,
     basic, auth, session, sessions, sid, jwt, otp); checked on the text as
     written and after mail addresses became `<mail>`;
   - after mail addresses became `<mail>`, it holds a token-like run
     (`looks_like_token`): 20 or more of `[A-Za-z0-9+/=_]` with at least four
     letters and two digits (one from 24 characters on), unless it is an
     absolute path of short plain segments; or a hyphenated run of 24 or
     more (any number of hyphens, UUIDs set aside) with a piece longer than
     four characters mixing letters and digits, or three such pieces.
   A slug or project that names a credential or looks like a token drops
   the finding. Otherwise mail addresses become `<mail>` and whitespace
   collapses. The item: stage `idea`,
   horizon `next`, owner `claude`, campaign `obs-triage`, the evidence as a
   note. At most five a day, counted over reruns (findings over the limit are
   announced as a count). Before the first write, the slugs are reserved in
   the day file (a stop right after leaves only unused numbers), then the
   digest naming every finding as undecided goes into the outbox, then each
   finding's hint is recorded right before its write (so a finding is never
   filed twice and a stop is never silent); only
   the final result says what was created. Right before each write `work
   show` checks that the slug is still free (only the ledger's own "not
   found" counts as free). Residual risk: the ledger API has no create-only
   write (`expected_updated_at` refuses missing items), so another writer
   creating the same `obs-` slug in the seconds between check and write
   would be overwritten. A write that failed or is undecided is named in the digest
   by its slug ("nicht (sicher) angelegt") and the day is `failed`; if it
   did not land, the next review meets it again.
7. The final result replaces the planned one in the outbox
   (`undelivered.json`, by its `id`, written atomically under a lock). Then each
   waiting result is handed to macmini (`obs_ctl.py deliver`), which sends
   the digest through Nyxmon's Telegram notifier: `🔎 Obs-Triage <date>: N
   neue Auffälligkeiten` with one line per item (`• obs-<date>-<n> [severity]`),
   plus one line per finding whose ledger write failed or is undecided;
   `high` findings are marked ‼️. Telegram is outside the estate, so the
   digest carries no model text: only the checked slugs, the severities and
   fixed words; before each delivery every line of a waiting message must
   match that digest grammar (`digest_safe`; item lines only in results of
   the current outbox format), otherwise a fixed notice is sent instead.
   Slugs skip numbers an existing item already has; they are reserved in
   the day file before the digest names them. The ledger (the owner's own work app) gets the texts, with
   the withholding rules above as a best effort; accepted residual risk: a
   copied secret without a credential word nearby that does not look like a
   token (short, letters only) can reach the ledger.
   macmini keeps no queue of its own: a result leaves the outbox only when
   macmini printed `obs-ctl: delivered` (Telegram acknowledged, or nothing
   to send); otherwise it goes out again with the next run. Each waiting
   result is tried on its own (one Telegram keeps refusing holds no other),
   and the outbox keeps the newest 30. A delivery whose confirmation got
   lost is sent again (a repeat rather than a loss). No new item and no
   problem: no message.

When Claude cannot run in any round (missing binary, an error result or
non-zero exit, the usage limit (HTTP 429: "Claude-Kontingent ist
aufgebraucht"), a timeout, an answer from another model or of the wrong
shape) there is **no fallback to another model**: the day is `skipped` and
the message says `übersprungen` with the reason (a fixed text with the exit
code or HTTP status; Claude's own diagnostics stay in the log). Any
other failure (pack, ledger list) is `failed` with its error type; details
are in the log. macmini keeps each
result; its status endpoint reports the triage age to Nyxmon ("Daily
evidence pack and triage fresh"), which moves only when a triage ran and its
message reached Telegram.

Run reports: `~/.local/state/obs-triage/runs/<date>-<HHMMSS>-<pid>.json`, one per
attempt (the model's final answer, its `known` matches, every dropped
finding with the reason, and per round its duration and the queries it
ran, without their results; written before any ledger item refers to it);
dry runs write `<date>-<HHMMSS>-<pid>.dry.json` and change no state. The
state directory is owner-only (0700; the JSON files it writes, run reports
included, are 0600; the lock files keep the umask's mode): the reports hold
the model's full answer, withheld texts included.

## `launchd-check`

Reads `launchctl print` for this machine's own jobs (plists in
`/Library/LaunchDaemons` and `~/Library/LaunchAgents` whose labels start with
`de.wersdoerfer.`, `local.`, `eu.coreso.`, `org.ops-library.` or
`com.ollama.`). A job is in a crash loop when its `runs` rose by 5 or more
since the previous sample (`launchd-sample.json`) and its last exit code is
not 0. A plist that launchd has not loaded (`launchctl print` exit 113,
"Could not find service", e.g. a job kept unloaded on purpose) is skipped: it
cannot loop and does not count as an error. A job whose `launchctl print`
fails otherwise or times out counts in `errors` and keeps its last good
counter, and the sample advances only after macmini accepted the report. The report goes to macmini (`obs_ctl.py launchd`); Nyxmon's "Studio
launchd crash loops" check is critical on a loop and warns on a report older than 45
minutes or with `errors` above 0 (a genuine sampling failure).

## `weekly`

Writes `weekly-brief.md` (date filled in) as
`~/workspaces/ws-work-planning/coordination/katharina/obs-weekly.md` and
starts it with that folder's `run.sh` on the main account (`ACCOUNT=main`).
The worker reviews the week's packs and triage results read-only, writes
`ws-work-planning/reviews/observability-weekly-<date>.md` and files items
only for new findings (campaign `obs-weekly`). Its report lands in
`obs-weekly.out` like any Katharina worker's.

## Variables

| Variable | Default |
|----------|---------|
| `OBS_TRIAGE_HOST` | `root@macmini.tailde2ec.ts.net` |
| `OBS_TRIAGE_CTL` | `/usr/bin/python3 -I /usr/local/lib/obs-daily/obs_ctl.py --config /etc/obs-daily/config.json` |
| `OBS_TRIAGE_STATE` | `~/.local/state/obs-triage` |
| `OBS_TRIAGE_KATHARINA` | `~/workspaces/ws-work-planning/coordination/katharina` |
| `OBS_TRIAGE_CLAUDE_CONFIG_DIR` | `~/.claude-katharina` |
| `OBS_TRIAGE_SSH_BIN`, `OBS_TRIAGE_WORK_BIN`, `OBS_TRIAGE_CLAUDE_BIN`, `OBS_TRIAGE_LAUNCHCTL` | `ssh`, `work`, `claude`, `launchctl` |

## Studio install

The three LaunchAgents `de.wersdoerfer.obs-triage` (daily 07:30),
`de.wersdoerfer.obs-launchd-check` (every 600 s) and `de.wersdoerfer.obs-weekly`
(Monday 08:30), logs in `~/Library/Logs/`, and their reload script are kept
in `tools/obs-triage/chezmoi/` until the tool is released; then they move
into the dotfiles repository (`private_Library/LaunchAgents/`,
`run_onchange_after_reload-obs-triage.sh.tmpl`, and the three plist names in
the Studio-only block of `.chezmoiignore`, see `chezmoiignore.patch`). The
jobs run from `~/projects/agent-stuff`, so they work once that checkout is
fast-forwarded to a commit that contains this tool.

## Tests

```sh
cd tools/obs-triage && python3.14 -m unittest discover -s tests -t .
```

Hermetic: stub `ssh`, `work` and `claude` scripts.
