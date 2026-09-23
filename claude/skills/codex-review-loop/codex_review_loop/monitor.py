"""Pure state machine for the review monitor. No IO, no clock - the runner feeds
events and the current time, so this is fully unit-testable.

Codex reports a finished turn with `turn.completed` and a failed one with
`turn.failed`. It can think for minutes without printing anything, so the
runner also reports growth of the session record as activity; only a reviewer
that neither prints nor records anything for `stall_timeout` is stalled.
"""
from dataclasses import dataclass

from .states import (INVALID, PROVIDER_ERROR, STALLED, KIND_DEADLINE,
                     KIND_FORBIDDEN_TOOL, KIND_PROVIDER, KIND_STALL)


@dataclass(frozen=True)
class Decision:
    action: str               # "continue" | "kill" | "finish"
    state: str | None = None  # None: classify from the completed turn
    kind: str | None = None


class Monitor:
    def __init__(self, *, started_at, stall_timeout, global_deadline,
                 exit_grace=30.0):
        self.stall_timeout = stall_timeout
        self.exit_grace = exit_grace
        self.global_deadline_at = started_at + global_deadline
        self.last_activity_at = started_at
        self.thread_id = None
        self.completed_at = None
        self.turn_failure = None
        self.errors = []
        self.forbidden = []

    def note_activity(self, now):
        self.last_activity_at = now

    def on_event(self, event, now):
        self.last_activity_at = now
        etype = event.get("type")
        if etype == "thread.started" and self.thread_id is None:
            self.thread_id = event.get("thread_id")
        elif etype == "turn.completed":
            self.completed_at = now
        elif etype == "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else error
            self.turn_failure = str(message or "turn failed")
        elif etype == "error":
            self.errors.append(str(event.get("message") or "error"))
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "collab_tool_call":
            self.forbidden.append(f"collab_tool_call:{item.get('tool')}")

    def decide(self, now, proc_alive):
        if self.forbidden:
            return Decision("kill" if proc_alive else "finish", INVALID,
                            KIND_FORBIDDEN_TOOL)
        if self.turn_failure is not None:
            return Decision("kill" if proc_alive else "finish", PROVIDER_ERROR,
                            KIND_PROVIDER)
        if not proc_alive:
            return Decision("finish")
        if self.completed_at is not None:
            # The turn is over; give Codex time to write its final message and
            # exit, then stop waiting for an exit that may never come.
            if now - self.completed_at > self.exit_grace:
                return Decision("kill")
            return Decision("continue")
        if now > self.global_deadline_at:
            return Decision("kill", STALLED, KIND_DEADLINE)
        if now - self.last_activity_at > self.stall_timeout:
            return Decision("kill", STALLED, KIND_STALL)
        return Decision("continue")
