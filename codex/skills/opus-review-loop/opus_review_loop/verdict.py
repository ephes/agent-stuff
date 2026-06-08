"""Parse Claude Opus review verdicts from terminal review text only.

Never scan the whole transcript: prompts and hook output can contain REVIEW:
examples, so transcript scans can accept prompt text as a verdict. Fail closed:
anything unparseable is INVALID, never CLEAN.
"""
import re
from .states import CLEAN, ISSUES, INVALID

_VERDICT_RE = re.compile(r"^REVIEW: (CLEAN|ISSUES)$", re.MULTILINE)
_ITEM_RE = re.compile(
    r"^\s*\d+\.\s*\[(Critical|Warning|Suggestion)\]\s*([^:]+(?::\d+)?):\s*(.+?)\s*$"
)


def extract_final_assistant_text(agent_end_event):
    """Return the concatenated text-block content of the last assistant message,
    or None if there is no assistant message. Returns an empty string if the
    last assistant message has no text-type blocks."""
    messages = agent_end_event.get("messages") or []
    last = None
    for msg in messages:
        if msg.get("role") == "assistant":
            last = msg
    if last is None:
        return None
    parts = []
    content = last.get("content")
    if isinstance(content, str):
        return content
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


def extract_claude_assistant_text(event):
    """Return text from a Claude Code stream-json assistant event, if present."""
    message = event.get("message") or {}
    if message.get("role") != "assistant":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


def extract_claude_result_text(event):
    """Return the terminal result text from a Claude Code result event."""
    if event.get("type") != "result":
        return None
    result = event.get("result")
    return result if isinstance(result, str) else None


def parse_verdict(text):
    """Return (state, items). state is CLEAN, ISSUES, or INVALID."""
    if not text:
        return INVALID, []
    matches = list(_VERDICT_RE.finditer(text))
    if not matches:
        return INVALID, []
    # ISSUES: parse numbered items after the first ISSUES verdict. Claude often
    # repeats or contradicts verdict lines. A parseable ISSUES block dominates
    # any later CLEAN line so a stray trailing CLEAN cannot erase findings.
    for issue_match in (m for m in matches if m.group(1) == "ISSUES"):
        tail = text[issue_match.end():]
        items = []
        for line in tail.splitlines():
            m = _ITEM_RE.match(line)
            if m:
                items.append({
                    "severity": m.group(1),
                    "path": m.group(2).strip(),
                    "message": m.group(3).strip(),
                })
        if items:
            return ISSUES, items
    final = matches[-1]
    if final.group(1) == "CLEAN":
        return CLEAN, []
    return INVALID, []
