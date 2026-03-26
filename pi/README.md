# Pi Assets

Use this directory for Pi-specific public assets.

Expected contents:

- `skills/` for reusable Pi skills
- optional example keybindings or settings when they are intentionally public

Current migrated assets:

- `skills/commit-ready`
- `skills/commit-workflow`
- `skills/review-handoff`, including `scripts/gather-changes.sh`

Still private in chezmoi:

- `~/.pi/agent/AGENTS.md`
- `~/.pi/agent/keybindings.json`
- Pi-specific install glue that links the installed `~/.pi/agent/skills/...` paths back to this repo

Install strategy:

- reusable Pi skills live in this public repo
- chezmoi manages private Pi config and directory-level symlinks from `~/.pi/agent/skills/<skill>` to `~/projects/agent-stuff/pi/skills/<skill>`
- skills with helper assets, such as `review-handoff/scripts/gather-changes.sh`, are linked as whole directories rather than file-by-file
