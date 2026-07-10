"""Extract and validate Claude's strict structured review verdict."""
from .states import CLEAN, ISSUES, INVALID


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


def extract_claude_structured_output(event):
    """Return the JSON-schema-validated payload from a terminal result event."""
    if event.get("type") != "result":
        return None
    value = event.get("structured_output")
    return value if isinstance(value, dict) else None


def validate_structured_verdict(value):
    """Return ``(state, items, error)`` with a diagnostic for invalid output."""
    if value is None:
        return INVALID, [], "missing structured output"
    if not isinstance(value, dict) or set(value) != {"verdict", "findings"}:
        return INVALID, [], "structured output must contain only verdict and findings"
    verdict = value.get("verdict")
    findings = value.get("findings")
    if verdict not in (CLEAN, ISSUES) or not isinstance(findings, list):
        return INVALID, [], "structured output has an invalid verdict or findings array"
    items = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {"severity", "path", "message"}:
            return INVALID, [], "structured output contains a malformed finding"
        severity = finding.get("severity")
        path = finding.get("path")
        message = finding.get("message")
        if severity not in ("Critical", "Warning", "Suggestion"):
            return INVALID, [], "structured output contains an invalid severity"
        if not isinstance(path, str) or not path.strip():
            return INVALID, [], "structured output contains an empty finding path"
        if not isinstance(message, str) or not message.strip():
            return INVALID, [], "structured output contains an empty finding message"
        items.append({"severity": severity, "path": path.strip(),
                      "message": message.strip()})
    if verdict == CLEAN and items:
        return INVALID, [], "CLEAN structured verdict must have no findings"
    if verdict == ISSUES and not items:
        return INVALID, [], "ISSUES structured verdict must include findings"
    return verdict, items, None
