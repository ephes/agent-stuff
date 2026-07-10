"""Pure state machine for the review monitor. No IO, no clock - the runner feeds
events and the current time, so this is fully unit-testable."""
from __future__ import annotations

from dataclasses import dataclass
import os
from .states import CRASHED, INVALID, STALLED, STALLED_RETRY, PROVIDER_ERROR
from .verdict import (
    extract_claude_assistant_text,
    extract_claude_structured_output,
    validate_structured_verdict,
)

# One registry drives both Claude's launch allowlist and the monitor. The only
# monitor-only exception is Claude Code's internal --json-schema transport.
INSPECTION_TOOLS = ("Read", "Grep", "Glob")
ALLOWED_REVIEW_TOOLS = frozenset((*INSPECTION_TOOLS, "StructuredOutput"))


@dataclass(frozen=True)
class Decision:
    action: str          # "continue" | "kill" | "finish"
    state: str | None    # terminal state when action in ("kill", "finish")


class Monitor:
    def __init__(self, *, started_at, stall_timeout, retry_grace, global_deadline,
                 review_root):
        self.started_at = started_at
        self.stall_timeout = stall_timeout
        self.retry_grace = retry_grace
        self.global_deadline_at = started_at + global_deadline
        self.last_event_at = started_at
        self.verdict_state = None      # set only by a successful terminal result
        self.verdict_items = []
        self.assistant_text = None
        self.cost = None
        self.provider_error = None     # finalError when provider gives up
        self.retry_until = None        # retry_deadline timestamp, or None
        self.structured_output = None
        self.tool_uses = []
        self.forbidden_tool_uses = []
        self.invalid_error = None
        self.review_root = os.path.realpath(review_root)

    def _target_error(self, name, tool_input):
        if name == "StructuredOutput":
            return None
        if not isinstance(tool_input, dict):
            return f"malformed Claude {name} tool input"

        if name == "Read":
            target = tool_input.get("file_path") or tool_input.get("path")
            if not isinstance(target, str) or not target:
                return "malformed Claude Read target"
        else:
            target = tool_input.get("path", ".")
            if not isinstance(target, str) or not target:
                return f"malformed Claude {name} target"

        if target.startswith("~"):
            return f"out-of-scope Claude {name} target: {target}"

        if name == "Glob":
            pattern = tool_input.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                return "malformed Claude Glob pattern"
            pattern_parts = pattern.replace("\\", "/").split("/")
            if os.path.isabs(pattern) or pattern.startswith("~") or ".." in pattern_parts:
                return f"out-of-scope Claude Glob pattern: {pattern}"

        candidate = target if os.path.isabs(target) else os.path.join(self.review_root, target)
        candidate = os.path.realpath(candidate)
        try:
            inside = os.path.commonpath((self.review_root, candidate)) == self.review_root
        except ValueError:
            inside = False
        if not inside:
            return f"out-of-scope Claude {name} target: {target}"
        return None

    def _record_tool_use(self, name, tool_input):
        if not isinstance(name, str) or not name:
            entry = {"tool": "<unnamed>",
                     "input": tool_input if isinstance(tool_input, dict) else {}}
            self.tool_uses.append(entry)
            self.forbidden_tool_uses.append(entry)
            self.invalid_error = "forbidden Claude tool use: unnamed tool"
            return
        entry = {"tool": name, "input": tool_input if isinstance(tool_input, dict) else {}}
        self.tool_uses.append(entry)
        if name not in ALLOWED_REVIEW_TOOLS:
            self.forbidden_tool_uses.append(entry)
            self.invalid_error = f"forbidden Claude tool use: {name}"
            return
        target_error = self._target_error(name, tool_input)
        if target_error is not None:
            self.forbidden_tool_uses.append(entry)
            self.invalid_error = target_error

    def _inspect_tool_use(self, event):
        if event.get("type") == "assistant":
            content = (event.get("message") or {}).get("content") or []
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self._record_tool_use(block.get("name"), block.get("input"))
        elif event.get("type") == "stream_event":
            inner = event.get("event") or {}
            block = inner.get("content_block") or {}
            if inner.get("type") == "content_block_start" and block.get("type") == "tool_use":
                name = block.get("name")
                tool_input = block.get("input")
                # Inspection inputs can be empty at stream start and arrive only
                # in the later complete assistant event. Still reject forbidden
                # tool names immediately, but defer target validation until the
                # complete input exists.
                if name not in INSPECTION_TOOLS or tool_input:
                    self._record_tool_use(name, tool_input)

    def on_event(self, event, now):
        self.last_event_at = now
        self._inspect_tool_use(event)
        etype = event.get("type")
        if etype == "assistant":
            self.assistant_text = extract_claude_assistant_text(event)
        elif etype == "result":
            if event.get("is_error") or event.get("subtype") != "success":
                self.provider_error = (
                    event.get("api_error_status")
                    or event.get("terminal_reason")
                    or event.get("subtype")
                    or "claude review failed"
                )
                return
            self.structured_output = extract_claude_structured_output(event)
            self.cost = event.get("total_cost_usd")
            (self.verdict_state, self.verdict_items,
             structured_error) = validate_structured_verdict(self.structured_output)
            if structured_error and self.invalid_error is None:
                self.invalid_error = structured_error
        # Pi-style retry events are retained for harness parity. Claude Code
        # stream-json does not currently emit them, so Claude internal retries
        # remain bounded by stall_timeout/global_deadline and fail closed.
        elif etype == "auto_retry_start":
            delay_s = (event.get("delayMs") or 0) / 1000.0
            self.retry_until = now + delay_s + self.retry_grace
        elif etype == "auto_retry_end":
            self.retry_until = None
            if event.get("success") is False:
                self.provider_error = event.get("finalError") or "provider gave up"

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
