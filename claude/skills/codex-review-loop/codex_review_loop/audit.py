"""Prove what ran, from Codex's own session record.

`codex exec --json` does not say which model answered, and it does not report
every tool call: a subagent spawn observed during the boundary canary appeared
in the session record but not in the event stream. The session record (the
"rollout" file under `$CODEX_HOME/sessions`) does carry both - a `turn_context`
with the model and effort for every turn, and every tool call the model made.
So the verdict is only accepted after that record has been read and it shows:

- at least one turn, and every turn on the pinned model and effort - and,
  when the caller asked for a cyber access program, under that program;
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
#: gpt-6.1-sol runs sandboxed shell commands; the others are the plain shell tool
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


MAX_RECORD_BYTES = 1024 * 1024
MAX_EVIDENCE = 4096
MAX_FIELD_CHARS = 512


def _records(fh):
    number = 0
    while True:
        raw = fh.readline(MAX_RECORD_BYTES + 1)
        if not raw:
            return
        number += 1
        oversized = len(raw) > MAX_RECORD_BYTES
        if oversized:
            while raw and not raw.endswith(b"\n"):
                raw = fh.readline(MAX_RECORD_BYTES + 1)
            yield number, None
        else:
            yield number, raw


def _remember(audit, field, value):
    target = getattr(audit, field)
    if (value is not None and (not isinstance(value, str) or len(value) > MAX_FIELD_CHARS)):
        audit.error = audit.error or "malformed or oversized audit field"
    elif len(target) >= MAX_EVIDENCE:
        audit.error = audit.error or "incomplete audit: evidence ceiling exceeded"
    else:
        target.append(value)


@dataclass
class Audit:
    path: str | None = None
    models: list = field(default_factory=list)
    efforts: list = field(default_factory=list)
    access_programs: list = field(default_factory=list)
    #: `codex_error_info` tags of failed turns, e.g. "cyber_policy".
    error_infos: list = field(default_factory=list)
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
    try:
        return _audit_session(path, audit)
    except UnicodeError:
        audit.error = audit.error or "session record is not UTF-8"
    except OSError:
        audit.error = audit.error or "cannot read session record: I/O failure"
    return audit


def _audit_session(path, audit):
    if path is None:
        audit.error = audit.error or "no session record found for this review"
        return audit
    try:
        fh = open(path, "rb")
    except OSError as exc:
        audit.error = audit.error or f"cannot read session record: {exc}"
        return audit
    with fh:
        for number, raw in _records(fh):
            if raw is None:
                audit.error = audit.error or f"incomplete audit: oversized record at line {number}"
                continue
            try:
                line = raw.decode("utf-8")
            except UnicodeError:
                audit.error = audit.error or f"session record line {number} is not UTF-8"
                continue
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                audit.error = audit.error or f"session record line {number} is not JSON"
                continue
            if not isinstance(record, dict):
                continue
            kind = record.get("type")
            if not isinstance(kind, str):
                audit.error = audit.error or f"malformed record type at line {number}"
                continue
            payload = record.get("payload")
            if kind in ("session_meta", "turn_context", "response_item", "event_msg") and not isinstance(payload, dict):
                audit.error = audit.error or f"malformed relevant envelope at line {number}"
                continue
            payload = payload if isinstance(payload, dict) else {}
            if kind in ("response_item", "event_msg") and not isinstance(payload.get("type"), str):
                audit.error = audit.error or f"malformed payload type at line {number}"
                continue
            # Structural, never a substring search: tool output in the record
            # carries the reviewed code, which may itself say "reroute".
            if _is_reroute(kind) or _is_reroute(payload.get("type")):
                _remember(audit, "reroutes", f"line {number}: {kind}/{payload.get('type')}")
            if kind == "session_meta":
                version = payload.get("cli_version")
                if isinstance(version, str) and len(version) <= MAX_FIELD_CHARS:
                    audit.cli_version = version or audit.cli_version
                source = payload.get("source")
                if isinstance(source, dict) and "subagent" in source:
                    _remember(audit, "forbidden", "session is a subagent thread")
            elif kind == "turn_context":
                _remember(audit, "models", payload.get("model"))
                _remember(audit, "efforts", payload.get("effort"))
                _remember(audit, "access_programs", payload.get("cyber_access_program"))
            elif kind in DELEGATION_RECORDS:
                _remember(audit, "forbidden", kind)
            elif kind == "response_item" and payload.get("type") in (
                    "function_call", "custom_tool_call"):
                if (not isinstance(payload.get("name"), str) or not payload["name"]
                        or not isinstance(payload.get("namespace"), (str, type(None)))):
                    if payload.get("namespace") == "collaboration":
                        _remember(audit, "forbidden", "collaboration.<malformed>")
                    audit.error = audit.error or f"malformed tool fields at line {number}"
                    continue
                label = _tool_label(payload)
                if len(label) > MAX_FIELD_CHARS:
                    label = label[:MAX_FIELD_CHARS - 1] + "…"
                    audit.error = audit.error or f"oversized tool label at line {number}"
                _remember(audit, "tool_uses", label)
                if (payload.get("namespace") in FORBIDDEN_NAMESPACES
                        or payload.get("name") not in ALLOWED_TOOLS
                        or payload.get("namespace") not in (None, "functions")):
                    _remember(audit, "forbidden", label)
            elif kind == "event_msg" and payload.get("type") == "item_completed":
                item = payload.get("item")
                if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                    audit.error = audit.error or f"malformed item type at line {number}"
                    continue
                if isinstance(item, dict) and item.get("type") in DELEGATION_ITEMS:
                    _remember(audit, "forbidden", item["type"])
            error = payload.get("error") if kind == "event_msg" else None
            if isinstance(error, dict) and isinstance(
                    error.get("codex_error_info"), str):
                _remember(audit, "error_infos", error["codex_error_info"])
    return audit


def judge(audit, *, model, effort, access_program=None):
    """Return None when the record proves the pinned run, else the reason.

    The access program is checked only when one was asked for: without the
    flag the server picks it, and the harness pins the model instead."""
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
    if access_program is not None:
        wrong_programs = sorted({str(p) for p in audit.access_programs
                                 if p != access_program})
        if wrong_programs:
            return (f"turn ran under cyber access program "
                    f"{', '.join(wrong_programs)}, not {access_program}")
    if audit.reroutes:
        return "session record shows a model reroute: " + "; ".join(audit.reroutes)
    return None
