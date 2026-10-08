---
name: multi-agent-coordination
description: Use when coordinating several agent workers at once - acting as the coordinator of a campaign, dispatching or resuming workers, writing worker briefs, pacing Claude/Codex subscription quota, bundling owner approvals, or closing out worker results. Provider-neutral; shared by Claude, Codex and Pi coordinators. Builds on work-ledger and cross-agent-review-cycle.
---

# Multi-Agent Coordination

How one coordinator runs many workers without losing state, burning the wrong
quota, or overloading the owner. The work app contract is in `work-ledger`;
review gates are in `cross-agent-review-cycle` (driven by `codex-review-loop`,
`claude-review-loop` or `pi-review-loop`). This skill does not repeat them.

## Roles

- **Coordinator** only coordinates: reads the work app, decides, writes briefs,
  dispatches and resumes workers, verifies their claims, relays to the owner.
  Implementation, builds, tests, reviews, merges, deploys, installs and
  investigations go to workers, even when they look quick.
- **Clerk** (an optional bookkeeping agent acting for the coordinator, under
  the coordinator's `work-ledger` rules): verifies pushes itself with
  `git ls-remote` before recording them, updates work-app items, creates one
  owner request per item, reports usage, and summarizes owner responses without
  consuming them. The coordinator still owns the decisions.
- **Scouts** are read-only workers that find ready, valuable slices and return
  a ranked list; the coordinator (or clerk) records the chosen ones as `idea`
  items. Prefer security and data-loss bugs, broken CI, and well-specified
  backlog items.
- **Implementation workers** never write to the work app; they report, and the
  coordinator or clerk verifies before recording.
- **Spawning is tool-specific**: Claude Code uses its Agent tool (resume with
  SendMessage); Codex uses its collaboration agents or herdr panes (`herdr
  agent prompt`); Pi uses herdr panes. Workers never see the coordinator's
  conversation, so every brief is self-contained.
- **Spawn workers directly** from the coordinator. A lead agent that spawns
  its own sub-agents hands back early and loses track of them.
- **Split work** roughly evenly between the Claude and Codex subscriptions.
  Codex workers run `gpt-6.1-sol` at low effort; their review gate is
  `claude-review-loop --model claude-opus-5-5 --effort high`.

## State and owner decisions

- The work app is the source of truth, not chat history. Long coordinator
  sessions get compacted; anything that matters is on an item before the turn
  ends.
- Stages are distinct claims (`work-ledger` stage ladder). Verify a worker's
  claim yourself before recording it, and read the full test or build log
  (for example `grep -E 'SKIP|FAIL|ERROR'`) before closing an item; a summary or
  the tail of a log is not evidence.
- Owner decisions arrive as work-app responses. Act on one through a worker,
  record the outcome, then consume it. The app never executes anything.
- Reduce owner load: bundle several branches of one repo into one integration
  branch so the owner approves once. For stacked branches (for example security
  fixes touching the same files), base each on the previous unmerged branch and
  state the merge order in the request.

## Quota pacing

- Spend the subscription whose weekly window resets sooner while it has
  headroom; save the other.
- A worker's review gate spends the reviewer's quota, not the implementer's
  (Codex reviews of Claude workers spend Codex). Review-heavy workers burn the
  implementer's quota slowly, so scale parallelism to the target burn rate
  (roughly 10-12 Claude workers for ~3%/h of a weekly window).
- Usage reporting is mandatory. Keep the weekly windows fresh in the work app
  (Claude "Weekly · all models", Codex weekly; only those) at session start,
  whenever handling worker results, and on every periodic check (at least
  hourly while a campaign runs). Claude: read the desktop app's usage tool
  (`get_usage`), then `work usage report --provider claude --window "Weekly · all models" --used <pct> --resets-at <iso>
  --observed-at now --source "claude-desktop get_usage"`. Codex: `work usage
  collect-codex`. Stale usage in the work app is a coordinator bug.

## Periodic checks

- While a campaign runs, schedule a recurring check every 30-60 minutes
  (Claude Code: CronCreate or `/loop`; Codex: its own scheduler or herdr). Each
  check reads unconsumed owner responses and newly approved items, checks
  running workers, reports usage, and dispatches the next approved or queued
  work within the pacing budget.
- Scheduled checks only fire while the coordinator is idle, so run the same
  check whenever handling results. Remove the schedule when the campaign ends.

## Worker brief checklist

Every brief states the item slug, goal, acceptance criteria, and:

- **Worktree**: `git fetch`, then a fresh worktree under
  `~/workspaces/ws-<slug>/` from the base the brief names: `origin/<default
  branch>` unless the slice is stacked on a predecessor branch (read the repo's
  `AGENTS.md`: the default branch is not always `main`, e.g. django-cast uses
  `develop`). `~/projects` is read-only for agents: no builds, tests, stash,
  pull, checkout, restore, commit or rm there (they may hold uncommitted owner
  work); `git fetch` and `worktree add` from there are fine. The opt-in hook
  `tools/guard-projects` enforces this.
- **Scratch**: a unique `mktemp -d` directory per worker. Shared scratch paths
  get overwritten by other workers.
- **Delivery**: feature branch, push only after
  `~/projects/agent-stuff/tools/guard-projects/bin/check-push-remote` passes
  (origin under `github.com/ephes/`; otherwise report, never push), verify with
  `git ls-remote`. No merge,
  deploy or install without owner approval (exception: fixes to the agent
  tooling in agent-stuff may be merged by the agent).
- **Review**: independent gate via the installed harness per
  `cross-agent-review-cycle`. After 2 rounds that are not clean, park the
  slice and ask the owner instead of looping. Use public APIs or allowlists,
  not home-made HTTP, streaming or delete-safety layers.
- **Unclear cases**: if a case does not clearly match the brief's rule, report
  it instead of acting.
- **Hygiene**: commit messages without AI or tool mentions; docs and changelog
  updated in the same change.
- **Versions**: in repos with version chains (e.g. ops-library's
  `galaxy.yml`), feature branches never bump the version or add a changelog
  version header; write entries under "Unreleased". The merge agent assigns
  the version at merge time, above origin's latest.
- **Concurrent pushes**: before merging, fetch; if origin moved, rebase and
  rerun the tests.
- **Parallel test infra**: molecule or docker tests use instance and container
  names unique to the worker (e.g. suffixed with the slug).
- **Native/Xcode**: each worker creates its own simulator and derived-data
  path and deletes the simulator afterwards. Never a physical device without
  explicit owner approval. Prebuilt artifacts (e.g. FFI builds) may be copied
  from another worktree only when their inputs (crates, project.yml) match.
- **Closeout**: a merge agent removes the slice's worktree once the merge is
  verified on the remote; otherwise at item closeout (`work-ledger`,
  Worktrees and closeout).
- **Lessons**: a worker or coordinator that appends a lesson to
  agent-stuff's `docs/review-cycle-log.md` does it in its own agent-stuff
  worktree and merges and pushes it immediately in a small commit (fetch/rebase
  first); never leave the log uncommitted, because a later shutdown strands it.

## Infrastructure and safety

- Deploy a new service exactly like the existing ones (homelab: ops-library
  role + ops-control playbook, Traefik routing per
  `ops-control/docs/TRAEFIK_SECURITY.md`, app login, SOPS secret, backup,
  monitoring check, dashboard tile). Do not invent new mechanisms; ask the owner
  instead.
- Dotfiles: edit the chezmoi source and apply only the targets you changed
  (`chezmoi apply <target>`). A full apply reverts unrelated drift.
- Destructive actions (`rm -rf`, cleanups, remote writes) may be blocked by
  permission policy. Then write a guarded script that defaults to a dry run and
  hand it to the owner. The owner's shell is fish: wrap bash syntax in
  `bash -c '...'`.
- Cleanup guard rails: check writability first; never remove a clone that
  others borrow objects from (git alternates); check commit containment against
  all remote refs, tags included. Prefer `tools/workspace-gc`.
- Restricted areas stay untouched (e.g. a stopped investigation). Real financial
  or personal data only in attended sessions with explicit owner authorization.
  Never print or commit tokens.
