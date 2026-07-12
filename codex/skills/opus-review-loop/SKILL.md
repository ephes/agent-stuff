---
name: opus-review-loop
description: Legacy compatibility alias for claude-review-loop. Use only when an existing workflow explicitly invokes opus-review-loop; delegate the review to the canonical configurable Claude gate with the Opus model.
---

# Legacy Opus Review Loop Alias

Use `claude-review-loop` for new workflows. Preserve this alias only for callers
that have not migrated yet.

The legacy executable forwards to the canonical harness with Opus as its
default:

```bash
python3 ~/projects/agent-stuff/codex/skills/opus-review-loop/bin/opus-review-loop \
  --repo "$PWD" --run-dir "$(mktemp -d)/claude-review"
```

Follow the canonical skill's lifecycle, evidence, exit-code, and scoped-CLEAN
rules. Do not maintain a separate review implementation here.
