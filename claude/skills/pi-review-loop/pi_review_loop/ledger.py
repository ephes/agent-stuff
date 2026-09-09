"""Pi records its rounds in the same per-slice ledger as the Claude harness.

A slice's round history is a property of the slice, not of the reviewer that
happened to run a given round - so a slice reviewed by Pi and then by Claude is
one history, and the stopping rules see all of it.
"""
from ._shared import ledger as _shared

CONVERGED = _shared.CONVERGED
PROGRESS = _shared.PROGRESS
ESCALATE = _shared.ESCALATE
append_round = _shared.append_round
assess = _shared.assess
path_for = _shared.path_for
read_rounds = _shared.read_rounds
record_for = _shared.record_for

__all__ = ["CONVERGED", "PROGRESS", "ESCALATE", "append_round", "assess",
           "path_for", "read_rounds", "record_for"]
