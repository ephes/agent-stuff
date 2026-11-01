# codex-quota-guard

Refuses Codex work while the Codex subscription limit is used up. Python 3
stdlib only.

Codex does not stop at 100% of its rate-limit window when the account has
paid credits: the call runs and spends credits. On 2026-11-01 a coordinator
started two reviews and a worker two days after the weekly window had filled,
because nothing refused.

The guard reads the newest rate-limit reading from Codex's own session records
(`$CODEX_HOME/sessions/**/rollout-*.jsonl`, default `~/.codex`; the same source
as `work usage collect-codex`). It blocks while any window (weekly or 5-hour)
is at or above the limit and its reset time has not passed. Only the windows
and the event time are read; no session content and no credit balance.

```sh
tools/codex-quota-guard/bin/codex-quota-guard            # exit 0 OK, 3 blocked
tools/codex-quota-guard/bin/codex-quota-guard --json     # machine-readable status
tools/codex-quota-guard/bin/codex-quota-guard --quiet    # print only when blocked
```

| Variable | Effect |
|----------|--------|
| `CODEX_QUOTA_ALLOW_CREDITS=1` | Do not block (the owner decided a credit-funded run is fine); the message still says so |
| `CODEX_QUOTA_MAX_PERCENT` | Block from this percentage instead of 100 (0 < value <= 100) |
| `CODEX_HOME` | Where Codex keeps its session records |

Without any reading (a fresh machine, or only Pi in use) it does not block and
says the limit was not checked. A reading is only as fresh as the last Codex
session on this machine; Pi's openai-codex calls draw on the same subscription
but write no Codex records.

Users: `codex-review-loop` and `pi-review-loop` call it before every review
(`PROVIDER_ERROR`, `failure_kind` `quota` for Codex). Launchers that start
`codex exec` directly live outside this repository and must call it first;
the owner's Codex worker launcher (`coordination/codex/run.sh` in the
work-planning folder, not in this repo) does.

Tests: `cd tools/codex-quota-guard && python3.14 -m unittest discover -s tests -t .`
