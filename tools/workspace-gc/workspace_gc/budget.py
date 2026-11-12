"""Time budgets for one run: a per-step deadline and a whole-run deadline.

A deadline is set for the current thread with `step(seconds)` (nested steps
keep the earlier of the two deadlines). Long filesystem walks call `check()`
once per directory, and git and du subprocesses cap their own timeout with
`cap()`, so a step that runs out of time stops at the next directory or
subprocess instead of running on. Outside any step both are no-ops.

The deadline lives in a contextvar: worker threads of a ThreadPoolExecutor
start without one and set their own per checkout.
"""

from __future__ import annotations

import contextlib
import contextvars
import time

_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "workspace_gc_deadline", default=None)


TIME_LIMIT = "run time limit reached"


class StepTimeout(Exception):
    """The current step (or the whole run) ran out of time."""


def _now() -> float:
    return time.monotonic()


@contextlib.contextmanager
def step(seconds: float | None, run_deadline: float | None = None):
    """Run the body with a deadline of `seconds` from now, never later than
    `run_deadline` (a monotonic timestamp) or an enclosing step. None or a
    value <= 0 for `seconds` means no step limit of its own."""
    candidates = [d for d in (_deadline.get(), run_deadline) if d is not None]
    if seconds is not None and seconds > 0:
        candidates.append(_now() + seconds)
    token = _deadline.set(min(candidates) if candidates else None)
    try:
        yield
    finally:
        _deadline.reset(token)


@contextlib.contextmanager
def unbounded():
    """Run the body without any deadline (for the destructive step of a
    removal, which must never be interrupted half-way by a budget)."""
    token = _deadline.set(None)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining() -> float | None:
    d = _deadline.get()
    return None if d is None else d - _now()


def check() -> None:
    left = remaining()
    if left is not None and left <= 0:
        raise StepTimeout("time limit reached")


def cap(timeout: float) -> float:
    """`timeout`, shortened to what is left of the current deadline. Raises
    StepTimeout when nothing is left."""
    left = remaining()
    if left is None:
        return timeout
    if left <= 0:
        raise StepTimeout("time limit reached")
    return max(0.01, min(timeout, left))


class RunClock:
    """The whole-run deadline (monotonic), or none."""

    def __init__(self, max_seconds: float | None):
        self.deadline = _now() + max_seconds if max_seconds and max_seconds > 0 else None

    def expired(self) -> bool:
        return self.deadline is not None and _now() >= self.deadline
