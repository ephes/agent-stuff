"""Terminal review states. A review ends in exactly one of these.

The set is the siblings' set, so a caller that knows one harness's states knows
this one's. What went wrong inside a failed state is in `failure_kind`.
"""

CLEAN = "CLEAN"
ISSUES = "ISSUES"
INVALID = "INVALID"
CRASHED = "CRASHED"
STALLED = "STALLED"
STALLED_RETRY = "STALLED_RETRY"
PROVIDER_ERROR = "PROVIDER_ERROR"

# States that mean "do not commit; not a usable clean review".
FAILED = frozenset({INVALID, CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR})
ALL = frozenset({CLEAN, ISSUES} | FAILED)

# failure_kind values. They refine a FAILED state; they never make one usable.
KIND_MODEL_MISMATCH = "model_mismatch"      # a turn ran on another model/effort
KIND_MODEL_UNPROVEN = "model_unproven"      # no session record proves the model
KIND_FORBIDDEN_TOOL = "forbidden_tool"      # delegation or an unlisted tool
KIND_PROVIDER = "provider"                  # capacity, rate limit, turn failed
KIND_STALL = "stall"                        # no activity for --stall-timeout
KIND_DEADLINE = "deadline"                  # --review-deadline exceeded
KIND_CRASH = "crash"                        # exited without a completed turn
KIND_VERDICT = "verdict"                    # final message not the schema
KIND_PREFLIGHT = "preflight"                # failed before Codex was started
KIND_INTERRUPTED = "interrupted"            # Ctrl-C during the review
KIND_LEDGER = "ledger"                      # the slice round could not be recorded
