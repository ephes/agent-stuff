---
name: coordinator-start
description: Use when (re)starting the owner's coordinator session in ~/projects/matters - after a restart, a crash, a compaction that lost track, or a new day ("Koordinator starten", "coordinator-start", "übernimm die Koordination"). Loads the coordination rules, reconstructs the owner's current mandate from the ledger, runs the periodic check once, reports a short German status in chat and sets up exactly one recurring 30-minute check.
---

# Coordinator Start

Restart procedure for the coordinator session in `~/projects/matters`. The
owner steers by talking into this session (owner decision 2026-11-16); this
skill rebuilds the session's working state from durable sources, never from
old session transcripts.

## 1. Load the rules

Load `multi-agent-coordination` and `work-ledger` (they reference
`cross-agent-review-cycle` for review gates). Their rules apply unchanged; in
particular the owner's chat instructions are authoritative and get recorded in
the ledger (`multi-agent-coordination`, **Planning and dispatch order**).
Standing safety rules for every worker brief are in
`~/workspaces/ws-work-planning/coordination/katharina/_rules-common.txt`; a
brief references that file as binding instead of copying it.

## 2. Reconstruct the mandate

The owner's mandate (allowed repos, goals, exclusions, capacity limits,
duration) and later chat instructions live as notes "owner chat <date>: ..."
in the ledger:

- `work show coordinator-mandate` and `work notes coordinator-mandate`
  (project `matters`, the standing coordination item). The newest note wins
  where notes conflict; a note that names an end date has expired after it.
  If the item does not exist yet, create it on the owner's first mandate
  (`work upsert coordinator-mandate --title "Koordinator: Auftrag des Owners"
  --summary "..." --project matters --stage implementing --owner claude
  --checked-at now`) and record each later instruction as a note.
- `work items` filtered to stage `implementing`, `pushed` and `parked`, and the
  notes of items the mandate names, for work in flight.
- `work responses` for unconsumed owner answers.

If no mandate is recorded, say so in the status report and dispatch only what
the owner assigns in chat. Never widen a mandate on a scout's or worker's
suggestion.

## 3. Run the periodic check once, then report

Run the check below once now. Then report in German in chat, briefly: the
mandate and its limits, quota per pool, what runs, bottlenecks (merge backlog,
autoround pause, blocked items) and the next steps you will take.

## 4. Schedule exactly one recurring check

Claude Code: `CronList` first; if a coordinator check already exists, keep it
and do not add another. Otherwise `CronCreate` with `cron: "7,37 * * * *"`,
`recurring: true` and the prompt below verbatim. Recurring jobs expire after 7
days and die with the session, so this skill re-creates the job on every
restart. Run the same check whenever you handle worker results; scheduled
checks fire only while the session is idle.

## Periodic check prompt

```text
Periodic coordinator check (coordinator-start).
1. Usage: work usage status --max-age 30m --provider claude. Exit 0: the Studio's usage-collect LaunchAgent keeps
   both Claude pools fresh (it runs work usage collect-codex too; a Codex reading is only as new as the last Codex session).
   Otherwise see why in ssh studio 'cat ~/.local/state/usage-collect/latest.txt' (every step's latest outcome and output)
   and report the stale pools by hand on the Studio:
   ~/projects/agent-stuff/tools/claude-usage-read/bin/claude-usage-read --report --pool claude;
   ~/projects/agent-stuff/tools/claude-usage-read/bin/claude-usage-read ~/.claude-katharina --report --pool claude-katharina;
   work usage collect-codex.
   Only if claude-usage-read cannot read the main account: read get_usage and report each weekly window it shows
   ("Weekly · all models", "Weekly · Fable", ...) with
   work usage report --provider claude --pool claude --window "<window>" --used N --resets-at <iso> --observed-at now --source "claude-desktop get_usage".
2. work responses: act on each response that belongs to this coordinator, record the outcome, then work consume <id>.
   Leave responses that belong to other coordinators (e.g. the photos coordinator) unconsumed.
3. herdr --machine claascraft workspace list (look only; never type into panes from this check).
4. Codex (~/workspaces/ws-work-planning/coordination/codex): feeder running (readlink feeder.lock; kill -0 that PID),
   queue length (queue.txt), running jobs (ps -axo pid,etime,command | grep '[r]un.sh'), tail autoround.log,
   autoround.off and autoround.pause (pause reason), autoround.state; finished reports = *.out containing
   "## Runner closeout" that are new since the last check. Katharina clerks (coordination/katharina):
   finished *.out reports and running run.sh jobs.
5. Merging runs by itself (owner 2026-11-16: local handoff, nothing may lie around): coordination/katharina/automerge.sh,
   run by the feeder every loop, starts a clerk for every finished Codex job (parked.txt line whose <brief>.out has
   "## Runner closeout", not queued, not running) that is in neither codex/merged.txt nor codex/dropped.txt (up to
   KMAX=4 at once, one per repo, each job once). Verify that it runs: automerge.off is ABSENT, automerge.log has recent
   lines (starts, drops, quota state) and merged.txt/dropped.txt keep growing; read new merge-<job>.out reports.
   Backlog = finished jobs in neither file (no ls-remote; legacy jobs pushed before 2026-11-16 still count as merged
   once their branch is gone from GitHub). Start a clerk by hand only for a job automerge does not cover: listed in
   automerge.started, its clerk no longer running and no merged/dropped line (failed clerk), or while automerge.off
   exists. Then render merge-tpl.md like automerge.sh does (or write a brief like it: repos without overlap with
   running clerks, _rules-common.txt binding) and start it:
   cd ~/workspaces/ws-work-planning/coordination/katharina && nohup ./run.sh <name> > logs/<name>.runner 2>&1 &
   Keep the Codex queue from running dry before the Codex reset, within the owner's mandate.
6. Report briefly in German in chat only when something changed (finished jobs, merges, pauses, failures,
   owner questions). Record owner instructions and outcomes in the ledger. Never read old session transcripts.
```

## Runner reference

- Codex (ws-work-planning `coordination/codex/`): `run.sh <brief>` runs one
  Codex job from `<brief>.md` plus `COMMON.md` and appends a runner closeout
  to `<brief>.out`; `feeder.sh` starts jobs from `queue.txt` (up to `MAX`,
  quota guard first; stop with `touch stop.flag`); `autoround.sh` refills the
  queue from scout rounds with the merge-backlog brake, one open branch per
  repo and the empty-round stop (`multi-agent-coordination`, **Quota
  pacing**); `queue.txt` is the operational Codex dispatch list. Start the
  feeder detached: `nohup ./feeder.sh >> feeder.log 2>&1 &` (its lock refuses
  a second copy). The brake limits are environment variables of the feeder
  (it passes them to `autoround.sh`): for example
  `BACKLOG_MAX=20 BACKLOG_HOURS=48 nohup ./feeder.sh >> feeder.log 2>&1 &`
  when the owner wants a looser brake; changing them means stopping the
  feeder (`touch stop.flag`, wait for it to exit, remove the flag) and
  starting it again.
- Automatic merge clerks (`coordination/katharina/automerge.sh`, header
  comment has the details): the feeder runs it first on every loop. Codex
  jobs commit on a local `codex-q/*` branch in their clone
  (`~/workspaces/ws-cx-<job>/<repo>`) and push nothing. For each finished job
  in neither `codex/merged.txt` nor `codex/dropped.txt` it renders
  `merge-tpl.md` to `merge-<job>.md` (clone path, branch, head SHA) and starts
  `run.sh merge-<job>`, at most `KMAX` (4, feeder environment) at once, never
  on a repo that a running clerk's brief names, and each job only once
  (`automerge.started`; remove a line to let it retry). A clone with nothing
  to hand off goes to `dropped.txt` directly. It skips starts while
  `claude-usage-read` reports the Katharina weekly usage at or above 90%
  (read on atlas when the local read fails), and skips that check (logged
  once) when the usage cannot be read. `touch automerge.off` disables it;
  starts, drops and skips are in `automerge.log`. The clerk merges locally,
  pushes only the integration branch and appends the job to `merged.txt` (or
  `dropped.txt` with the reason); `workspace-gc` then removes the Codex clone
  after 48 hours.
- Katharina clerks (`coordination/katharina/`): `run.sh <brief>` runs a
  headless Claude worker on the second account (`CLAUDE_CONFIG_DIR=
  ~/.claude-katharina`, Opus 5.5 by default, `MODEL=` overrides) from
  `<brief>.md`; output in `<brief>.out`, full log in `logs/<brief>.log`.
  Merge clerks create no remote branch. Only for a legacy job that still
  pushed its `codex-q/*` branch to GitHub (briefs from before 2026-11-16) the
  brief grants the one exception to the common rules' "never delete remote
  branches": that branch is deleted once its merge is verified, which is how
  the backlog brake sees a legacy job as merged.
  `_rules-common.txt` holds the binding safety rules (decision classes,
  B-class plan review, worktrees under `~/workspaces/ws-<slug>/`,
  `~/projects` read-only, gates, push checks, no secrets, no data deletion,
  resource limits, no transcript or home-wide scans, foreground work, German
  final report).
