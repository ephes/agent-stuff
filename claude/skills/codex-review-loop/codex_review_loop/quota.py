"""The shared Codex quota guard (agent-stuff/tools/codex-quota-guard).

Codex runs on paid credits once the subscription window is used up instead of
refusing, so the harness checks the newest rate-limit reading before it starts
a review and fails closed while the limit is used up.
"""
import os
import sys

from ._shared import REPO_ROOT

GUARD_DIR = os.path.join(REPO_ROOT, "tools", "codex-quota-guard")

if GUARD_DIR not in sys.path:
    sys.path.insert(0, GUARD_DIR)

try:
    from codex_quota_guard import ALLOW_ENV, check  # noqa: F401
except ImportError as exc:  # pragma: no cover - deployment error, not a code path
    raise ImportError(
        f"the Codex quota guard is missing, expected at {GUARD_DIR}; install "
        "agent-stuff with its tools directory"
    ) from exc
