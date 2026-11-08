"""ReviewResult: the single structured outcome of one review, written to result.json."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from .states import CLEAN, PASSING


@dataclass
class ReviewResult:
    state: str
    items: list
    model: str
    cost: float | None
    started_at: float
    ended_at: float
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)
    redactions: list = field(default_factory=list)
    effort: str | None = None
    structured_output: dict | None = None
    tool_uses: list = field(default_factory=list)
    forbidden_tool_uses: list = field(default_factory=list)
    denied_tool_uses: list = field(default_factory=list)
    baseline_ref: str | None = None
    baseline_commit: str | None = None
    slice_id: str | None = None
    round: int | None = None
    convergence: dict | None = None
    review_copy: dict | None = None
    error: str | None = None

    @property
    def scoped_clean(self):
        """A CLEAN verdict over a bundle that skipped or truncated content is only
        'clean within provided scope', not absolute."""
        return self.state == CLEAN and bool(
            self.skipped_files or self.truncations or self.redactions
        )

    @property
    def scoped_pass(self):
        """A passing result (CLEAN or SUGGESTIONS_ONLY) whose bundle skipped,
        truncated or redacted content: it passes only within that scope.
        Unlike the slice ledger's `scoped`, which records the bundle scope for
        any state, this is about a passing result only."""
        return self.state in PASSING and bool(
            self.skipped_files or self.truncations or self.redactions
        )

    def to_dict(self):
        d = asdict(self)
        d["scoped_clean"] = self.scoped_clean
        d["scoped_pass"] = self.scoped_pass
        d["duration_s"] = round(self.ended_at - self.started_at, 3)
        return d

    def write(self, path):
        # Preflight the complete portable JSON before touching any receipt.
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True, allow_nan=False)
        fd, temporary = tempfile.mkstemp(prefix=".result-", dir=os.path.dirname(os.path.abspath(path)))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fd = None
                fh.write(payload)
                fh.flush()
            os.replace(temporary, path)
        finally:
            if fd is not None:
                os.close(fd)
            if os.path.exists(temporary):
                os.unlink(temporary)
