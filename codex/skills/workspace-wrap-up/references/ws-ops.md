# Ops Workspace Wrap-Up Rules

Use these rules for workspaces created by:

```bash
cd /Users/jochen/projects/ops-control
just workspace-create <name>
```

## Workspace Shape

- Workspace root: `/Users/jochen/workspaces/ws-<name>`
- `ops-control`: workspace worktree on `workspace/<name>` by default
- `ops-library`: workspace worktree on `workspace/<name>` by default
- `specs/`: symlink to `$OPS_META_PATH/specs`
- Service repos such as `nyxmon`, `fastdeploy`, and `homelab` usually live
  under `/Users/jochen/projects`, unless `PROJECTS_ROOT` points to a workspace
  clone.

## Discovery

Inspect at least:

```bash
git -C <workspace>/ops-control status --short
git -C <workspace>/ops-library status --short
```

Also inspect service repos named by the task or touched during the session, for
example:

```bash
git -C /Users/jochen/projects/nyxmon status --short
git -C /Users/jochen/projects/fastdeploy status --short
git -C /Users/jochen/projects/ops-meta status --short
```

Do not assume only `ops-control` and `ops-library` changed.

## Validation

From `ops-control`, run:

```bash
scripts/show-path-overrides.sh
```

If `ops-library` changed, run from `ops-control`:

```bash
just install-local-library
```

Use each changed repo's own `AGENTS.md`, `just --list`, and docs to choose
required checks. For role/deploy changes, the workspace AGENTS definition of
done may require `just test`, `just typecheck`, `just lint`, deployment, and
live verification.

## Commit Boundaries

- Commit `ops-control`, `ops-library`, `ops-meta`, and service repos separately.
- Never edit roles in `ops-control/collections/`; edit roles in `ops-library`.
- If `specs/` changed, commit the backing `$OPS_META_PATH` repo, not the symlink
  path inside the workspace.
- Keep secrets and local env files out of commits.

## Sync and Promotion

Run promotion commands from the workspace `ops-control` worktree.

To update workspace branches from `origin/main` and push workspace branches:

```bash
cd <workspace>/ops-control
just workspace-sync
```

To fast-forward promote workspace branches to `origin/main`:

```bash
cd <workspace>/ops-control
just workspace-promote
```

To do both:

```bash
cd <workspace>/ops-control
just workspace-sync-and-promote
```

These commands manage `ops-control` and `ops-library`. They do not promote
service repos such as `nyxmon`; handle those with normal repo-specific git
workflow after checking branch/upstream state.

## Final Report

Call out:

- Which repos were covered by workspace promotion
- Which service repos were pushed separately
- Any repos left dirty, uncommitted, or unpushed
- Whether deployment/live verification was done or intentionally deferred
