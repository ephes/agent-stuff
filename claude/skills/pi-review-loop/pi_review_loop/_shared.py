"""Locate the shared review machinery that lives with `claude-review-loop`.

The bundle and the slice ledger are reviewer-agnostic: the bundle is a redacted
view of a git worktree, and the ledger is the round history of one slice
whichever reviewer produced it. Both harnesses use the same implementation so
they cannot drift apart, which a copy of one of them already did once.
"""
import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
# agent-stuff/claude/skills/pi-review-loop/pi_review_loop -> agent-stuff
REPO_ROOT = os.path.realpath(os.path.join(_HERE, "..", "..", "..", ".."))
SHARED_SKILL = os.path.join(REPO_ROOT, "codex", "skills", "claude-review-loop")

if SHARED_SKILL not in sys.path:
    sys.path.insert(0, SHARED_SKILL)

try:
    from claude_review_loop import bundle, ledger  # noqa: F401
except ImportError as exc:  # pragma: no cover - deployment error, not a code path
    raise ImportError(
        "pi-review-loop needs the shared review machinery from "
        f"claude-review-loop, expected at {SHARED_SKILL}. Install the sibling "
        "skill from agent-stuff at the same relative path; a Pi-only deployment "
        "cannot build a redacted bundle on its own."
    ) from exc
