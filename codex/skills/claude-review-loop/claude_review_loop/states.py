"""Terminal review states. A review ends in exactly one of these."""

CLEAN = "CLEAN"
ISSUES = "ISSUES"
# The reviewer answered ISSUES, but every finding is a Suggestion: the round
# converged with nothing that blocks the commit gate. The harness derives it;
# the reviewer's schema still only offers CLEAN and ISSUES.
SUGGESTIONS_ONLY = "SUGGESTIONS_ONLY"
INVALID = "INVALID"
CRASHED = "CRASHED"
STALLED = "STALLED"
STALLED_RETRY = "STALLED_RETRY"
PROVIDER_ERROR = "PROVIDER_ERROR"

# States that mean "do not commit; not a usable clean review".
FAILED = frozenset({INVALID, CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR})
# Completed reviews that pass the gate (exit 0). SUGGESTIONS_ONLY still needs
# the caller's recorded proportionality decision and is never relabeled CLEAN.
PASSING = frozenset({CLEAN, SUGGESTIONS_ONLY})
# All valid states (used for validation/serialization sanity).
ALL = frozenset({CLEAN, ISSUES, SUGGESTIONS_ONLY} | FAILED)
