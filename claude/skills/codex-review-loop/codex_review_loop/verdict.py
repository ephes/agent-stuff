"""Parse the reviewer's final message against the verdict schema.

Codex is run with `--output-schema`, so its final message must be one JSON
object. Anything else - prose, a second object, a CLEAN with findings, an
ISSUES without any - is INVALID, never CLEAN.
"""
import json

from .states import CLEAN, ISSUES, INVALID

SEVERITIES = ("Critical", "Warning", "Suggestion")

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["CLEAN", "ISSUES"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "path": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["severity", "path", "message"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdict", "findings"],
    "additionalProperties": False,
}


def parse_verdict(text):
    """Return (state, items, structured, error)."""
    if text is None or not text.strip():
        return INVALID, [], None, "final message is empty"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return INVALID, [], None, f"final message is not JSON: {exc}"
    if not isinstance(data, dict) or set(data) != {"verdict", "findings"}:
        return INVALID, [], None, "final message does not match the verdict schema"
    verdict, findings = data["verdict"], data["findings"]
    if verdict not in ("CLEAN", "ISSUES") or not isinstance(findings, list):
        return INVALID, [], data, "final message does not match the verdict schema"
    items = []
    for finding in findings:
        if (not isinstance(finding, dict)
                or set(finding) != {"severity", "path", "message"}
                or finding["severity"] not in SEVERITIES
                or not all(isinstance(finding[k], str) and finding[k].strip()
                           for k in ("path", "message"))):
            return INVALID, [], data, "a finding does not match the verdict schema"
        items.append({"severity": finding["severity"],
                      "path": finding["path"].strip(),
                      "message": finding["message"].strip()})
    if verdict == "CLEAN" and items:
        return INVALID, [], data, "CLEAN verdict carries findings"
    if verdict == "ISSUES" and not items:
        return INVALID, [], data, "ISSUES verdict carries no findings"
    return (CLEAN if verdict == "CLEAN" else ISSUES), items, data, None
