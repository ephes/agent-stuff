"""Pi's review bundle is the shared bundle from `claude-review-loop`.

The bundle is Pi's starting point and the only part of the review that is
redacted: whatever it omits, the reviewer can only recover by finding it in its
repository copy. That is the same contract the sibling
harness's bundle already implements, and this module used to be a copy of an
older version of it - one that predated secret redaction, the external-diff and
textconv guards, the non-regular-file checks, and byte-exact decoding. A copy
that falls behind is worse than no copy, so this delegates instead.

The names are re-exported so `pi_review_loop.bundle` keeps its interface.
"""
from ._shared import bundle as _shared

BundleResult = _shared.BundleResult
build_bundle = _shared.build_bundle
EVIDENCE_BOUNDARY_TITLE = _shared.EVIDENCE_BOUNDARY_TITLE
EVIDENCE_BOUNDARY = _shared.EVIDENCE_BOUNDARY

__all__ = [
    "BundleResult",
    "build_bundle",
    "EVIDENCE_BOUNDARY_TITLE",
    "EVIDENCE_BOUNDARY",
]
