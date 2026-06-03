"""Terminal review states. A review ends in exactly one of these."""

CLEAN = "CLEAN"
ISSUES = "ISSUES"
INVALID = "INVALID"
CRASHED = "CRASHED"
STALLED = "STALLED"
STALLED_RETRY = "STALLED_RETRY"
PROVIDER_ERROR = "PROVIDER_ERROR"

# States that mean "do not commit; not a usable clean review".
FAILED = frozenset({INVALID, CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR})
# All valid states (used for validation/serialization sanity).
ALL = frozenset({CLEAN, ISSUES} | FAILED)
