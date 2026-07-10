"""Conservative secret redaction for review context before model egress."""
from __future__ import annotations

import fnmatch
import re
import shlex


SECRET_PATH_PATTERNS = (
    ".env", ".env.*", ".envrc", ".netrc", ".pypirc", "*.env",
    "*.pem", "*.key", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "*.p12",
)

SECRET_VALUE_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])AKIA[0-9A-Z]{16}"),
    re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])github_pat_[0-9A-Za-z_]{22,}"),
    re.compile(r"(?<![A-Za-z0-9_])glpat-[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])sk_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"(?<![A-Za-z0-9_])AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}"),
    re.compile(r"(?<![A-Za-z0-9_])pypi-[A-Za-z0-9_-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_=-]{10,}\.eyJ[A-Za-z0-9_=-]{10,}\.[A-Za-z0-9_=-]{8,}"),
    re.compile(r"(?i)(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"([a-z][a-z0-9+.-]*://[^\s:/@]*:)[^\s:/@]+(?=@)"),
)

_GENERIC_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?P<prefix>(?P<key_quote>['\"]?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P=key_quote)\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[A-Za-z0-9._~+/=_-]{16,})(?P=quote)"
)

_PRIVATE_KEY_BEGIN_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-----")
_PRIVATE_KEY_END_RE = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-----")
_REDACTED = "[redacted: secret value]"


def is_secret_path(path):
    basename = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(basename, pattern) for pattern in SECRET_PATH_PATTERNS)


def _is_secret_assignment_key(key):
    key = key.lower()
    compact = key.replace("_", "")
    if compact in {
        "key", "token", "secret", "password", "passwd", "pwd", "passphrase",
        "apikey", "apitoken", "accesskey", "accesstoken", "secretkey",
        "secrettoken", "privatekey", "privatetoken",
    }:
        return True
    parts = [part for part in key.split("_") if part]
    if any(part in {"token", "secret", "password", "passwd", "pwd", "passphrase"}
           for part in parts):
        return True
    return len(parts) >= 2 and tuple(parts[-2:]) in {
        ("api", "key"), ("access", "key"), ("private", "key"),
    }


def _redact_values(text):
    changed = False
    out = text
    for pattern in SECRET_VALUE_PATTERNS:
        def repl(match):
            nonlocal changed
            changed = True
            if match.lastindex:
                return f"{match.group(1)}{_REDACTED}"
            return _REDACTED
        out = pattern.sub(repl, out)

    def redact_assignment(match):
        nonlocal changed
        if not _is_secret_assignment_key(match.group("key")):
            return match.group(0)
        value = match.group("value")
        quoted = bool(match.group("quote"))
        entropy_markers = sum(char.isdigit() or char in ".+/~=" for char in value)
        if not quoted and entropy_markers < 2:
            return match.group(0)
        changed = True
        quote = match.group("quote")
        return f"{match.group('prefix')}{quote}{_REDACTED}{quote}"

    out = _GENERIC_ASSIGNMENT_RE.sub(redact_assignment, out)
    return out, changed


def _redact_key_line(text, in_block):
    if in_block:
        end = _PRIVATE_KEY_END_RE.search(text)
        if end is None:
            return _REDACTED, True, True
        prefix = _REDACTED if text[:end.start()].strip() else text[:end.start()]
        return prefix + text[end.start():], True, False

    begin = _PRIVATE_KEY_BEGIN_RE.search(text)
    if begin is None:
        return text, False, False
    end = _PRIVATE_KEY_END_RE.search(text, begin.end())
    if end is not None:
        return text[:begin.end()] + _REDACTED + text[end.start():], True, False
    tail = text[begin.end():]
    return text[:begin.end()] + (_REDACTED if tail.strip() else tail), True, True


def redact_text(text):
    """Return ``(redacted_text, changed)`` for free-form context."""
    if not text:
        return text, False
    out, changed, in_key_block = [], False, False
    for line in text.split("\n"):
        emitted, key_changed, in_key_block = _redact_key_line(line, in_key_block)
        emitted, value_changed = _redact_values(emitted)
        changed = changed or key_changed or value_changed
        out.append(emitted)
    return "\n".join(out), changed


def _diff_path(line):
    try:
        fields = shlex.split(line[len("diff --git "):])
    except ValueError:
        fields = line[len("diff --git "):].split()
    if len(fields) != 2:
        return "?"
    path = fields[1]
    return path[2:] if path.startswith("b/") else path


def _marker_path(line):
    """Return the exact path from an out-of-hunk ---/+++ file marker."""
    raw = line[4:].split("\t", 1)[0]
    if raw == "/dev/null":
        return None
    if raw.startswith('"'):
        try:
            fields = shlex.split(raw)
        except ValueError:
            return None
        raw = fields[0] if len(fields) == 1 else raw
    if raw.startswith(("a/", "b/")):
        return raw[2:]
    return None


def redact_diff(text):
    """Redact secret paths, tokens, and key blocks in a unified diff."""
    out, redacted_paths = [], []
    current_path, skip_file, in_key_block, in_hunk = "", False, False, False

    def note():
        if current_path and current_path not in redacted_paths:
            redacted_paths.append(current_path)

    for line in text.split("\n"):
        if line.startswith("\x1b["):
            raise OSError("ANSI escape sequence in git diff")
        if line.startswith("diff ") and not line.startswith("diff --git "):
            raise OSError(f"unsupported git diff header: {line}")
        if line.startswith("diff --git "):
            current_path = _diff_path(line)
            skip_file = is_secret_path(current_path)
            in_key_block = False
            in_hunk = False
            out.append(line)
            if skip_file:
                note()
                out.append("[redacted: secret-looking file not sent]")
            continue
        if skip_file:
            continue

        if line.startswith("@@"):
            in_hunk = True
            closing = line.find("@@", 2)
            if closing < 0:
                raise OSError(f"malformed git hunk header: {line}")
            header, heading = line[:closing + 2], line[closing + 2:]
            # Git may use a base64 key-body line as function context for the
            # next hunk. Preserve key-block state and redact that heading even
            # when it has none of the standalone token shapes.
            if in_key_block and heading.strip():
                leading = heading[:len(heading) - len(heading.lstrip())]
                heading, changed = leading + _REDACTED, True
            else:
                heading, changed = _redact_values(heading)
            if changed:
                note()
            out.append(header + heading)
            continue
        is_file_header = not in_hunk and line.startswith(("+++ ", "--- "))
        if is_file_header:
            marker_path = _marker_path(line)
            if marker_path is not None:
                current_path = marker_path
                if is_secret_path(current_path):
                    skip_file = True
                    note()
                    out.append(line)
                    out.append("[redacted: secret-looking file not sent]")
                    continue
        scannable = line.startswith(("+", "-", " ")) and not is_file_header
        if not scannable:
            # A long removed/added key can span unified-diff hunks. Hunk
            # metadata must not close the redaction state before its END marker.
            if in_key_block and (
                line == "" or line == "\\ No newline at end of file"
            ):
                out.append(line)
                continue
            in_key_block = False
            out.append(line)
            continue
        marker, content = line[0], line[1:]
        emitted, key_changed, in_key_block = _redact_key_line(content, in_key_block)
        emitted, value_changed = _redact_values(emitted)
        if key_changed or value_changed:
            note()
        out.append(marker + emitted)
    return "\n".join(out), redacted_paths
