"""ReviewResult: the single structured outcome of one review, written to result.json."""
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
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)
    error: str | None = None
    raw_verdict_line: str | None = None

    @property
    def scoped_clean(self):
        """A CLEAN verdict over a bundle that skipped or truncated content is only
        'clean within provided scope', not absolute."""
        return self.state == CLEAN and bool(self.skipped_files or self.truncations)

    def to_dict(self):
        d = asdict(self)
        d["scoped_clean"] = self.scoped_clean
        d["duration_s"] = round(self.ended_at - self.started_at, 3)
        return d

    def write(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
