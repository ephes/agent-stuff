"""Prove what ran, from Codex's own session record.

`codex exec --json` does not say which model answered, and it does not report
every tool call: a subagent spawn observed during the boundary canary appeared
in the session record but not in the event stream. The session record (the
"rollout" file under `$CODEX_HOME/sessions`) does carry both - a `turn_context`
with the model and effort for every turn, and every tool call the model made.
So the verdict is only accepted after that record has been read and it shows:

- at least one turn, and every turn on the pinned model and effort;
- no model reroute, which Codex records when the server answers with a model
  other than the one requested;
- only allowlisted tools, and no delegation of any kind.

A missing or unreadable record is a failure, not a pass: without it nothing
proves which model produced the verdict.
"""
import glob
import json
import os
from dataclasses import dataclass, field

#: Tools the reviewer may call. `exec` is the code-mode host through which
#: gpt-6-sol runs sandboxed shell commands; the others are the plain shell tool
#: names used when code mode is not in play, and the side-effect-free plan and
#: wait tools. Everything else fails the review, so a new Codex tool is refused
#: until someone decides it belongs here.
ALLOWED_TOOLS = frozenset({
    "exec", "wait", "exec_command", "write_stdin", "shell", "update_plan",
})
#: Namespaces whose tools are delegation, whatever their name.
FORBIDDEN_NAMESPACES = frozenset({"collaboration"})
#: Session-record items that only exist when work was delegated.
DELEGATION_ITEMS = frozenset({"SubAgentActivity", "CollabAgentToolCall"})
DELEGATION_RECORDS = frozenset({"inter_agent_communication_metadata"})


@dataclass
class Audit:
    path: str | None = None
    models: list = field(default_factory=list)
    efforts: list = field(default_factory=list)
    reroutes: list = field(default_factory=list)
    tool_uses: list = field(default_factory=list)
    forbidden: list = field(default_factory=list)
    cli_version: str | None = None
    error: str | None = None


def find_session_record(codex_home, thread_id):
    """Return the one session record for `thread_id`, or None."""
    if not thread_id or "/" in thread_id or "*" in thread_id:
        return None
    pattern = os.path.join(codex_home, "sessions", "*", "*", "*",
                           f"rollout-*-{glob.escape(thread_id)}.jsonl")
    matches = glob.glob(pattern)
    return matches[0] if len(matches) == 1 else None


def _is_reroute(kind):
    return isinstance(kind, str) and "reroute" in kind.lower()


def _tool_label(payload):
    name = payload.get("name") or "?"
    namespace = payload.get("namespace")
    return f"{namespace}.{name}" if namespace else name


def audit_session(path):
    audit = Audit(path=path)
    if path is None:
        audit.error = "no session record found for this review"
        return audit
    try:
        fh = open(path, encoding="utf-8")
    except OSError as exc:
        audit.error = f"cannot read session record: {exc}"
        return audit
    with fh:
        for number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                audit.error = f"session record line {number} is not JSON"
                return audit
            if not isinstance(record, dict):
                continue
            kind = record.get("type")
            payload = record.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            # Structural, never a substring search: tool output in the record
            # carries the reviewed code, which may itself say "reroute".
            if _is_reroute(kind) or _is_reroute(payload.get("type")):
                audit.reroutes.append(f"line {number}: {kind}/{payload.get('type')}")
            if kind == "session_meta":
                audit.cli_version = payload.get("cli_version") or audit.cli_version
                source = payload.get("source")
                if isinstance(source, dict) and "subagent" in source:
                    audit.forbidden.append("session is a subagent thread")
            elif kind == "turn_context":
                audit.models.append(payload.get("model"))
                audit.efforts.append(payload.get("effort"))
            elif kind in DELEGATION_RECORDS:
                audit.forbidden.append(kind)
            elif kind == "response_item" and payload.get("type") in (
                    "function_call", "custom_tool_call"):
                label = _tool_label(payload)
                audit.tool_uses.append(label)
                if (payload.get("namespace") in FORBIDDEN_NAMESPACES
                        or payload.get("name") not in ALLOWED_TOOLS
                        or payload.get("namespace") not in (None, "functions")):
                    audit.forbidden.append(label)
            elif kind == "event_msg" and payload.get("type") == "item_completed":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") in DELEGATION_ITEMS:
                    audit.forbidden.append(item["type"])
    return audit


def judge(audit, *, model, effort):
    """Return None when the record proves the pinned run, else the reason."""
    if audit.error:
        return audit.error
    if not audit.models:
        return "session record holds no turn, so nothing proves the model"
    wrong_models = sorted({str(m) for m in audit.models if m != model})
    if wrong_models:
        return f"turn ran on {', '.join(wrong_models)}, not {model}"
    wrong_efforts = sorted({str(e) for e in audit.efforts if e != effort})
    if wrong_efforts:
        return f"turn ran at effort {', '.join(wrong_efforts)}, not {effort}"
    if audit.reroutes:
        return "session record shows a model reroute: " + "; ".join(audit.reroutes)
    return None
