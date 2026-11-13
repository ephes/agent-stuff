"""Pure state machine for the review monitor. No IO, no clock - the runner feeds
events and the current time, so this is fully unit-testable.

Codex reports a finished turn with `turn.completed` and a failed one with
`turn.failed`. It can think for minutes without printing anything, so the
runner also reports growth of the session record as activity; only a reviewer
that neither prints nor records anything for `stall_timeout` is stalled.

A Codex that starts no thread within `startup_timeout` is stalled too, however
long the stall timeout: a working Codex reports `thread.started` within seconds
of its launch, and one that does not is waiting on something outside the
review - on macOS, a Gatekeeper dialog for a newly installed binary.
"""
import shlex
from dataclasses import dataclass

from .states import (INVALID, PROVIDER_ERROR, STALLED, KIND_DEADLINE,
                     KIND_FORBIDDEN_TOOL, KIND_PROVIDER, KIND_STALL)


@dataclass(frozen=True)
class Decision:
    action: str               # "continue" | "kill" | "finish"
    state: str | None = None  # None: classify from the completed turn
    kind: str | None = None
    error: str | None = None  # why the harness ends the run, when it does


def startup_hint(binary=None):
    """Where a launch that never starts a thread most likely waits."""
    check = ("`xattr -p com.apple.quarantine "
             + (shlex.quote(binary) if binary else "<native codex binary>") + "`")
    return ("On macOS the first launch of a newly installed or updated Codex "
            "can wait silently on a Gatekeeper dialog on the logged-in user's "
            f"screen: check the binary with {check}, approve it at that screen "
            "or clear the attribute, then rerun.")


class Monitor:
    def __init__(self, *, started_at, stall_timeout, global_deadline,
                 exit_grace=30.0, startup_timeout=None, binary=None):
        self.started_at = started_at
        self.binary = binary
        self.stall_timeout = stall_timeout
        self.startup_timeout = startup_timeout
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
            return Decision("kill", STALLED, KIND_DEADLINE, self._stalled(
                f"the review exceeded --review-deadline "
                f"({now - self.started_at:.0f}s)"))
        if (self.startup_timeout is not None and self.thread_id is None
                and now - self.started_at > self.startup_timeout):
            return Decision("kill", STALLED, KIND_STALL, self._stalled(
                f"Codex started no thread within --startup-timeout "
                f"({self.startup_timeout:g}s) of its launch"))
        if now - self.last_activity_at > self.stall_timeout:
            return Decision("kill", STALLED, KIND_STALL, self._stalled(
                f"Codex printed no event and grew no session record for "
                f"--stall-timeout ({self.stall_timeout:g}s)"))
        return Decision("continue")

    def _stalled(self, what):
        """One line: what ended the run, and - when Codex never started a
        thread - where it most likely waited."""
        if self.thread_id is not None:
            return what + "; the reviewer was killed"
        return (f"{what} and never started a thread; it was killed. "
                + startup_hint(self.binary))
