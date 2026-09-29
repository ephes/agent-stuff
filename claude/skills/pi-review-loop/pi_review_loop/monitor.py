"""Pure state machine for the review monitor. No IO, no clock — the runner feeds
events and the current time, so this is fully unit-testable."""
import re
from dataclasses import dataclass
from .states import CRASHED, INVALID, STALLED, STALLED_RETRY, PROVIDER_ERROR
from .verdict import extract_final_assistant_text, parse_verdict


#: The tools the harness enables with `--tools`. Anything else in the event
#: stream means an extension or a newer Pi added one, and the review is void.
ALLOWED_TOOLS = frozenset({"read", "bash", "edit", "write", "grep", "find", "ls"})

# A shell command that starts another agent is delegation. Pi has no sandbox,
# so this is a best-effort check on the command's words, not enforcement: it
# looks for an agent CLI in command position (line start, or after `;`, `&`,
# `|`, `(`, a backtick or `$(`), optionally behind a path, `env`, `exec`,
# `command`, `nohup` or `timeout N`.
_DELEGATION_RE = re.compile(
    r"(?:^|[;&|(`\n]|\$\()\s*"
    r"(?:(?:env|exec|command|nohup|timeout\s+\S+)\s+(?:\w+=\S*\s+)*)*"
    r"(?:\w+=\S*\s+)*"
    r"(?:\S*/)?(?:pi|claude|codex|opencode|gemini|aider)(?=\s|$|[;&|)`])")


def delegation_in(command):
    return isinstance(command, str) and _DELEGATION_RE.search(command) is not None


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
        self.tool_uses = []
        self.forbidden_tool_uses = []
        self.invalid_error = None

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
        if etype == "tool_execution_start":
            self._record_tool(event)
        elif etype == "agent_end":
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

    def _record_tool(self, event):
        name = event.get("toolName")
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        entry = {"tool": name if isinstance(name, str) else "<unnamed>",
                 "input": args}
        self.tool_uses.append(entry)
        if name not in ALLOWED_TOOLS:
            reason = f"forbidden Pi tool use: {entry['tool']}"
        elif name == "bash" and delegation_in(args.get("command")):
            reason = "delegation: the reviewer started another agent"
        else:
            return
        self.forbidden_tool_uses.append(entry)
        if self.invalid_error is None:
            self.invalid_error = reason

    def decide(self, now, proc_alive):
        if self.invalid_error is not None:
            return Decision("kill", INVALID)
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
