"""Parse Pi's review verdict from the final assistant message only.

Never scan the whole agent_end transcript: it echoes the prompt/bundle, which
contains REVIEW: examples, so a transcript scan can accept prompt text as a
verdict (false pass). Fail closed: anything unparseable is INVALID, never CLEAN.
"""
import re
from .states import CLEAN, ISSUES, INVALID

_VERDICT_RE = re.compile(r"^REVIEW: (CLEAN|ISSUES)$", re.MULTILINE)
_ITEM_RE = re.compile(
    r"^\s*\d+\.\s*\[(Critical|Warning|Suggestion)\]\s*([^:]+):\s*(.+?)\s*$"
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


def parse_verdict(text):
    """Return (state, items). state is CLEAN, ISSUES, or INVALID."""
    if not text:
        return INVALID, []
    matches = list(_VERDICT_RE.finditer(text))
    if not matches:
        return INVALID, []
    last = matches[-1]
    if last.group(1) == "CLEAN":
        return CLEAN, []
    # ISSUES: parse numbered items anywhere in the final assistant message.
    # Reviewers commonly list findings BEFORE the trailing `REVIEW: ISSUES`
    # line, so scanning only the text after the verdict dropped them and
    # mislabeled real ISSUES as INVALID. Scanning the whole final assistant
    # message is safe: it is Pi's own output, not the prompt/bundle (the
    # caller already restricts this text to the last assistant message).
    items = []
    for line in text.splitlines():
        m = _ITEM_RE.match(line)
        if m:
            items.append({
                "severity": m.group(1),
                "path": m.group(2).strip(),
                "message": m.group(3).strip(),
            })
    if not items:
        return INVALID, []
    return ISSUES, items
