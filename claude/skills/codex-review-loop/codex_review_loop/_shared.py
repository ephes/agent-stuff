"""Locate the shared review machinery that lives with `claude-review-loop`.

The bundle, the redaction rules, the slot pool and the slice ledger are
reviewer-agnostic. `pi-review-loop` already delegates to them rather than
keeping a copy, because a copy of the bundle once fell behind the original and
lost its secret redaction. This harness does the same.
"""
import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
# agent-stuff/claude/skills/codex-review-loop/codex_review_loop -> agent-stuff
REPO_ROOT = os.path.realpath(os.path.join(_HERE, "..", "..", "..", ".."))
SHARED_SKILL = os.path.join(REPO_ROOT, "codex", "skills", "claude-review-loop")

if SHARED_SKILL not in sys.path:
    sys.path.insert(0, SHARED_SKILL)

try:
    from claude_review_loop import bundle, ledger, lock, redact  # noqa: F401
except ImportError as exc:  # pragma: no cover - deployment error, not a code path
    raise ImportError(
        "codex-review-loop needs the shared review machinery from "
        f"claude-review-loop, expected at {SHARED_SKILL}. Install the sibling "
        "skill from agent-stuff at the same relative path; this harness cannot "
        "build a redacted bundle on its own."
    ) from exc
