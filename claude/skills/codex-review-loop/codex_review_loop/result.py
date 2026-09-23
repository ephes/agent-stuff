"""ReviewResult: the single structured outcome of one review, written to result.json.

The fields the siblings write are all here under the same names, so callers and
the shared ledger read one shape. The extra fields record what this harness
proved about the run: which model and effort every turn actually used, which
tools ran, and which Codex session the evidence came from.
"""
import json
from dataclasses import dataclass, field, asdict
from .states import CLEAN


@dataclass
class ReviewResult:
    state: str
    items: list
    model: str
    cost: float | None
    started_at: float
    ended_at: float
    effort: str | None = None
    failure_kind: str | None = None
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)
    redactions: list = field(default_factory=list)
    evidence_files: list = field(default_factory=list)
    baseline_ref: str | None = None
    baseline_commit: str | None = None
    slice_id: str | None = None
    round: int | None = None
    convergence: dict | None = None
    thread_id: str | None = None
    session_record: str | None = None
    observed_models: list = field(default_factory=list)
    observed_efforts: list = field(default_factory=list)
    tool_uses: list = field(default_factory=list)
    forbidden_tool_uses: list = field(default_factory=list)
    structured_output: dict | None = None
    error: str | None = None
    raw_verdict_line: str | None = None

    @property
    def scoped_clean(self):
        """A CLEAN verdict over a bundle that skipped, truncated, or redacted
        content is only 'clean within provided scope', not absolute."""
        return self.state == CLEAN and bool(
            self.skipped_files or self.truncations or self.redactions
        )

    def to_dict(self):
        d = asdict(self)
        d["scoped_clean"] = self.scoped_clean
        d["duration_s"] = round(self.ended_at - self.started_at, 3)
        return d

    def write(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
