"""Pure state machine for the review monitor. No IO, no clock — the runner feeds
events and the current time, so this is fully unit-testable."""
from dataclasses import dataclass
from .states import CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR
from .verdict import extract_final_assistant_text, parse_verdict


@dataclass(frozen=True)
class Decision:
    action: str          # "continue" | "kill" | "finish"
    state: str | None    # terminal state when action in ("kill", "finish")


class Monitor:
    def __init__(self, *, started_at, stall_timeout, retry_grace, global_deadline):
        self.started_at = started_at
        self.stall_timeout = stall_timeout
        self.retry_grace = retry_grace
        self.global_deadline_at = started_at + global_deadline
        self.last_event_at = started_at
        self.verdict_state = None      # set when agent_end arrives
        self.verdict_items = []
        self.verdict_text = None
        self.provider_error = None     # finalError when provider gives up
        self.retry_until = None        # retry_deadline timestamp, or None

    def note_output(self, now):
        """Record raw stdout activity that is not a structured event.

        Any output proves the review process is alive, so it resets the
        stall timer; otherwise a burst of non-JSON output (which carries
        no parseable event) could be mis-killed as STALLED while Pi is
        actively producing it.
        """
        self.last_event_at = now

    def on_event(self, event, now):
        self.last_event_at = now
        etype = event.get("type")
        if etype == "agent_end":
            text = extract_final_assistant_text(event)
            self.verdict_text = text
            self.verdict_state, self.verdict_items = parse_verdict(text or "")
        elif etype == "auto_retry_start":
            delay_s = (event.get("delayMs") or 0) / 1000.0
            self.retry_until = now + delay_s + self.retry_grace
        elif etype == "auto_retry_end":
            self.retry_until = None
            if event.get("success") is False:
                self.provider_error = event.get("finalError") or "provider gave up"

    def decide(self, now, proc_alive):
        if self.verdict_state is not None:
            return Decision("finish", self.verdict_state)
        if self.provider_error is not None:
            return Decision("kill", PROVIDER_ERROR)
        if not proc_alive:
            return Decision("finish", CRASHED)
        if now > self.global_deadline_at:
            return Decision("kill", STALLED)
        if self.retry_until is not None and now > self.retry_until:
            return Decision("kill", STALLED_RETRY)
        if self.retry_until is None and (now - self.last_event_at) > self.stall_timeout:
            return Decision("kill", STALLED)
        return Decision("continue", None)
