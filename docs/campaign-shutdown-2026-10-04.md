# Campaign shutdown — 2026-10-04

## Ready workflow delivery

Reviewed handoff propagation commit `4fa11411674fa87ddc880f15e65416693176e5dd`
was activated by the coordinator: original local main fast-forwarded from
`eaa98a2826c33206c465d254d73623954bffd3ab`. Seven validators, four installed
links, five canonical links and four fresh-session source decision checks passed.
These are source acceptance checks, not generated live prompt trials. Historical
review remains advisory; the approved Pi model mismatch remains blocked.

This non-default branch carries that unchanged implementation plus this docs-only
shutdown checkpoint. No new implementation review or broad tests were run at
shutdown. The shared original review log remains outside this change; its latest
preserved SHA-256 is
`b26fd317bc1e5d57e76c406e5e1b4437ef62fbf4bfe7bccbdcf1c271843fa41d`.
No default merge, deployment, link repointing or dotfile changes occur here.

## Restricted unfinished work — do not resume

The Echoport reproduction remains locally uncommitted in the isolated
`ws-echoport-retention-race/echoport` worktree on
`experiment/echoport-retention-race-reproduction`, based on
`51678035ef9c2b1299b4229220118ff7e7fbb7eb`. Last verified state comprised
four staged test/documentation files and unchanged product source. It was not
inspected, retried, reviewed or modified during shutdown.

Historical evidence: six synthetic baseline scenarios and Ruff/hooks passed.
OpenAI GPT-6.1 Sol HIGH round 1 returned three unresolved Warnings: UI observer
connection reuse, direct connection evidence before replacement, and child-timeout
scratch cleanup. This is incomplete, not CLEAN or accepted. Last verified compute
release was `2026-10-03T20:12:15.720158Z`, with zero owned survivors.
A reported safety restriction stops continuation; no workaround is authorized.

## Shutdown and restart

All three listed child agents (deadline_design, echoport_design and
retention_concurrency_design) were already completed; explicit interruption
confirmed that safe boundary. cast_audit and forward_check were not listed as
live. No active watches or owned execution sessions remain in this agent.
Files, worktrees and external safety copies are retained.

Restart steps:

1. Read this checkpoint and the workflow activation result before new work.
2. Verify the remote non-default workflow branch and exact activated commit;
   do not reapply activation or overwrite the shared dirty review log.
3. Treat Pi model mismatch as blocked; use only an explicitly approved available
   review path for newly authorized work.
4. Leave the restricted Echoport work untouched. A future restart requires the
   restriction to be resolved through the appropriate supported mechanism, then
   an explicit new scope and fresh validation slot. Existing evidence alone does
   not authorize repair, execution, commit or publication of that candidate.

The external shutdown receipt records the exact pushed checkpoint revision and
remote verification. No canonical planning or Site files are changed.
