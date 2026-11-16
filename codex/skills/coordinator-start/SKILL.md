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
1. Usage: read Claude main with get_usage, then
   work usage report --provider claude --window "Weekly · all models" --used N --resets-at <iso> --observed-at now --source "claude-desktop get_usage";
   work usage collect-codex;
   Katharina: ssh atlas '~/projects/agent-stuff/tools/claude-usage-read/bin/claude-usage-read ~/.claude-katharina'
   and report its used=/resets_at= with
   work usage report --provider claude --account katharina --window "Weekly · all models" --used N --resets-at <iso> --observed-at now --source "claude-usage-read atlas".
2. work responses: act on each response that belongs to this coordinator, record the outcome, then work consume <id>.
   Leave responses that belong to other coordinators (e.g. the photos coordinator) unconsumed.
3. herdr --machine claascraft workspace list (look only; never type into panes from this check).
4. Codex (~/workspaces/ws-work-planning/coordination/codex): feeder running (readlink feeder.lock; kill -0 that PID),
   queue length (queue.txt), running jobs (ps -axo pid,etime,command | grep '[r]un.sh'), tail autoround.log,
   autoround.off and autoround.pause (pause reason), autoround.state; finished reports = *.out containing
   "## Runner closeout" that are new since the last check. Katharina clerks (coordination/katharina):
   finished *.out reports and running run.sh jobs.
5. Merge backlog: parked codex-q/* branches not yet merged. Candidates are the lines of parked.txt
   (<brief> <repo> <branch>) whose job has FINISHED (<brief>.out contains "## Runner closeout") and is neither
   in queue.txt nor running (no `run.sh <brief>` process); queued or running jobs are not merge-ready. A finished
   candidate whose branch is still present per `git ls-remote --heads git@github.com:ephes/<repo>.git <branch>`
   is unmerged. For those that no running clerk covers -> write a clerk brief like
   coordination/katharina/r101-merge-a.md (repos without overlap with running clerks, _rules-common.txt binding,
   and state the one exception explicitly: delete each codex-q/* branch after verifying its merge on the remote
   integration branch) and start it:
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
- Katharina clerks (`coordination/katharina/`): `run.sh <brief>` runs a
  headless Claude worker on the second account (`CLAUDE_CONFIG_DIR=
  ~/.claude-katharina`, Opus 5.5 by default, `MODEL=` overrides) from
  `<brief>.md`; output in `<brief>.out`, full log in `logs/<brief>.log`.
  Merge-clerk briefs grant one exception to the common rules' "never delete
  remote branches": the merged `codex-q/*` branch is deleted once its merge
  is verified, which is how the autoround's backlog brake sees it as merged.
  `_rules-common.txt` holds the binding safety rules (decision classes,
  B-class plan review, worktrees under `~/workspaces/ws-<slug>/`,
  `~/projects` read-only, gates, push checks, no secrets, no data deletion,
  resource limits, no transcript or home-wide scans, foreground work, German
  final report).
