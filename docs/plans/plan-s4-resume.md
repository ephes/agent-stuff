# S4 planning skills — parked for finisher (2026-11-07)

Branch `plan-s4-skills` retains the held `3444433` changes and aligns both shared skills
with companion `ephes/work-ledger` branch `plan-s4-cli`. Merge these together only after the
review gate and full local checks. No live skills installation or chezmoi apply was performed.

The CLI contract is documented in the work-ledger README and its
`receipts/2026-11-plan-s4.md` resume note. In particular, `work next` defaults to one result,
filters all pages before limiting, selects Now designed/prototype with no open request,
and allows exact owner/pool names jochen/claude/codex/pi. Named and unknown worker owners are
excluded; re-read/check for active workers before optimistic claiming. Expedite never overrides
rank. Agents only append new items to Next/Later, never reorder or move to Now; proposals via
`work ask`. Reprioritization happens in owner chat at quota reset/weekly. Queue copies become
generated read-only snapshots; the coordinator's explicit-mapping import runs after deployment.

Validation: both skill-creator quick validators passed; repo frontmatter check found 22 skills,
zero problems; `git diff --check` passed. The README's eight hermetic unittest suites passed:
893 discovered, 7 expected live-canary/platform skips, no failures. No separate types/lint gate exists
for these prose changes and there is no repository-wide changelog.

Review remains **unavailable, not clean**. The earlier skills attempt and current companion CLI
attempt failed because the installed Claude OAuth session expired and could not be refreshed.
Current artifacts: workspace `review-cli-r1/result.json` / `events.jsonl`. Do not rerun an unchanged
failing authentication call. Repair auth outside the worker, then use the installed
`claude-review-loop --model claude-opus-5-5 --effort high` on the full feature delta.
The original held commit must be included; reviewing only the most recent alignment misses it.

Create a fresh review clone based on current main after integrating latest main into the feature,
apply `git diff main...plan-s4-skills --binary` as uncommitted changes there, and run the harness
with a new run directory, workspace lock/ledger dirs, and `--record-baseline`. Include the actual
CLI selection contract in a trusted context file. The companion resume note gives the same
procedure. Fix required findings and re-review only repair deltas using the baseline, bounded
at four rounds/repeated required finding. After both review gates and local checks pass,
merge both branches with `--no-ff`, rerun full local gates after merge, push main and verify
with `git ls-remote`. No PRs or branch deletion. Do not run/wait for Actions, deploy or import live queues.
