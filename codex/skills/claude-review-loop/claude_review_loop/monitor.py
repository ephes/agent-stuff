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

# How Claude Code answers a tool call its `dontAsk` permission mode refused
# (verified against Claude Code 2.1.x). An out-of-scope call answered with
# exactly this text returned no data, so it is recorded and the review goes on;
# any other answer invalidates the review. A reworded denial fails closed.
PERMISSION_DENIAL_HEAD = (
    "Permission to use {tool} has been denied because Claude Code is running "
    "in don't ask mode."
)
PERMISSION_DENIAL_GUIDANCE = (
    " IMPORTANT: You *may* attempt to accomplish this action using other tools "
    "that might naturally be used to accomplish this goal, e.g. using head "
    "instead of cat. But you *should not* attempt to work around this denial in "
    "malicious ways, e.g. do not use your ability to run tests to execute "
    "non-test actions. You should only try to work around this restriction in "
    "reasonable ways that do not attempt to bypass the intent behind this "
    "denial. If you believe this capability is essential to complete the user's "
    "request, STOP and explain to the user what you were trying to do and why "
    "you need this permission. Let the user decide how to proceed."
)


def _is_permission_denial(block, tool):
    """True only for a tool_result that is exactly Claude's denial of `tool`:
    one string or one text block, nothing else that could carry data."""
    if block.get("is_error") is not True:
        return False
    content = block.get("content")
    if isinstance(content, list):
        if len(content) != 1 or not isinstance(content[0], dict) \
                or content[0].get("type") != "text":
            return False
        content = content[0].get("text")
    head = PERMISSION_DENIAL_HEAD.format(tool=tool)
    return content in (head, head + PERMISSION_DENIAL_GUIDANCE)


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
        self.denied_tool_uses = []     # out-of-scope calls Claude itself refused
        self.pending_out_of_scope = {}  # tool_use id -> (entry, error)
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

    def _record_tool_use(self, name, tool_input, tool_use_id=None):
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
        if target_error is None:
            return
        if isinstance(tool_use_id, str) and tool_use_id:
            # Wait for Claude's answer: a permission denial is harmless.
            self.pending_out_of_scope[tool_use_id] = (entry, target_error)
            return
        self.forbidden_tool_uses.append(entry)
        self.invalid_error = target_error

    def _inspect_tool_result(self, event):
        content = (event.get("message") or {}).get("content") or []
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            pending = self.pending_out_of_scope.pop(block.get("tool_use_id"), None)
            if pending is None:
                continue
            entry, target_error = pending
            if _is_permission_denial(block, entry["tool"]):
                self.denied_tool_uses.append({**entry, "error": target_error})
            else:
                self.forbidden_tool_uses.append(entry)
                self.invalid_error = f"{target_error} (not denied by Claude)"

    def _inspect_tool_use(self, event):
        if event.get("type") == "assistant":
            content = (event.get("message") or {}).get("content") or []
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self._record_tool_use(block.get("name"), block.get("input"),
                                          block.get("id"))
        elif event.get("type") == "user":
            self._inspect_tool_result(event)
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
                    self._record_tool_use(name, tool_input, block.get("id"))

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
            if self.pending_out_of_scope:
                # A verdict with an unanswered out-of-scope call cannot count.
                _, target_error = next(iter(self.pending_out_of_scope.values()))
                self.invalid_error = f"{target_error} (no answer from Claude)"
                return Decision("kill", INVALID)
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
