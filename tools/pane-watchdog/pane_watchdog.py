"""Read-only scan of herdr panes for agents that silently wait.

herdr reports a pane that waits on a dialog or on the owner as ``idle``. This
module reads each pane with ``herdr [--machine M] pane read <id> --format
ansi`` and looks for:

- ``usage-dialog``: the ``/usage`` settings dialog is open
- ``trust-dialog``: the folder trust question is open
- ``permission-prompt``: a tool permission question ("Do you want to proceed?",
  "Esc to cancel") is open
- ``owner-question``: the turn has finished and the last message asks a question
- ``input-text``: the ``❯`` input line holds non-dim text (typed but not sent)

Dim text (SGR 2, ``ESC[2m``) in the input line is a prompt suggestion ("ghost
text"), not input, and is ignored; reading without ``--format ansi`` would make
it look like owner input. The scan only ever runs ``pane list`` and ``pane
read``; it never sends keys or text. Python 3 stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field

EXIT_NONE = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

SNIPPET_MAX = 120
DEFAULT_LINES = 80
DIALOG_TAIL = 30
FOOTER_MAX = 6
QUESTION_TAIL = 8
LOCAL = "local"
READ_ONLY_COMMANDS = (("pane", "list"), ("pane", "read"))

_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI = re.compile(r"\x1b\[([0-9;:?<>=]*)[ -/]*([@-~])")
_OTHER_ESC = re.compile(r"\x1b[@-Z\\-_]|\x1b[()][0-9A-Za-z]")
_RULE_CHARS = set("─━▔▁═")

_TRUST = re.compile(
    r"Do you trust the files in this folder|Yes, I trust this folder|"
    r"Is this a project you created or one you trust", re.IGNORECASE)
_USAGE = re.compile(r"Current week \(all models\)", re.IGNORECASE)
_USAGE_TABS = re.compile(r"Settings\s+Status\s+Config\s+Usage", re.IGNORECASE)
_PERMISSION = re.compile(r"\bDo you want to\b.*\?", re.IGNORECASE)
_ESC_CANCEL = re.compile(r"\bEsc to cancel\b", re.IGNORECASE)
_ASK_PHRASES = re.compile(
    r"\b(?:shall I|should I|do you want me|want me to|would you like|please confirm|"
    r"soll ich|sollen wir|möchtest du|willst du|bitte bestätige|bitte gib frei)\b",
    re.IGNORECASE)
_QUESTION_END = re.compile(r"\?[\s\"'“”‘’»«)\]*_`]*$")
_NOT_A_QUESTION = re.compile(r"Interrupted · What should Claude do instead\?")
_STATUS_PREFIXES = ("✻", "※", "❯", "⎿")


@dataclass
class Line:
    text: str  # everything printed on the line
    plain: str  # only the non-dim characters

    @property
    def stripped(self) -> str:
        return self.text.strip()


@dataclass
class Finding:
    machine: str
    pane: str
    kind: str
    snippet: str

    def line(self) -> str:
        return f"{self.machine}\t{self.pane}\t{self.kind}\t{self.snippet}"


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _apply_sgr(params: str, dim: bool) -> bool:
    codes = params.replace(":", ";").split(";") if params else ["0"]
    i = 0
    while i < len(codes):
        code = codes[i]
        if code in ("", "0", "22"):
            dim = False
        elif code == "2":
            dim = True
        elif code in ("38", "48", "58"):
            # extended colour: 5;n or 2;r;g;b - skip its arguments
            if i + 1 < len(codes) and codes[i + 1] == "5":
                i += 2
            elif i + 1 < len(codes) and codes[i + 1] == "2":
                i += 4
        i += 1
    return dim


def parse_ansi(raw: str) -> list[Line]:
    """Split ANSI output into lines, keeping the full text and the non-dim part."""
    raw = _OSC.sub("", raw)
    lines: list[Line] = []
    text: list[str] = []
    plain: list[str] = []
    dim = False
    pos = 0
    while pos < len(raw):
        char = raw[pos]
        if char == "\x1b":
            match = _CSI.match(raw, pos)
            if match:
                if match.group(2) == "m":
                    dim = _apply_sgr(match.group(1), dim)
                pos = match.end()
                continue
            match = _OTHER_ESC.match(raw, pos)
            pos = match.end() if match else pos + 1
            continue
        if char == "\n":
            lines.append(Line("".join(text), "".join(plain)))
            text, plain = [], []
        elif char == "\r" or (ord(char) < 32 and char != "\t"):
            pass
        else:
            text.append(char)
            if not dim:
                plain.append(char)
        pos += 1
    if text or plain:
        lines.append(Line("".join(text), "".join(plain)))
    return lines


def snippet(text: str) -> str:
    text = " ".join(text.replace("\xa0", " ").split())
    return text if len(text) <= SNIPPET_MAX else text[:SNIPPET_MAX - 1] + "…"


def _is_rule(line: Line) -> bool:
    stripped = line.stripped
    return len(stripped) >= 3 and stripped[:3] and set(stripped[:3]) <= _RULE_CHARS


def find_input_box(lines: list[Line]) -> tuple[int, int] | None:
    """Return (first, end) of the input box: the last ``❯`` line right below a rule.

    ``end`` is the index of the closing rule. Option lists inside dialogs
    (``❯ 1. Yes``) and earlier user messages are not directly below a rule.
    The box only counts when it is the bottom of the screen: at most
    FOOTER_MAX status lines, and no rule, message or prompt, may follow it.
    A box left in scrollback above a dialog is not the current one.
    """
    for index in range(len(lines) - 1, -1, -1):
        if not lines[index].stripped.startswith("❯"):
            continue
        above = index - 1
        while above >= 0 and not lines[above].stripped:
            above -= 1
        if above < 0 or not _is_rule(lines[above]):
            continue
        for end in range(index + 1, len(lines)):
            if _is_rule(lines[end]):
                footer = [line for line in lines[end + 1:] if line.stripped]
                if len(footer) > FOOTER_MAX or any(
                        _is_rule(line) or line.stripped.startswith(("❯", "⏺")) for line in footer):
                    return None
                return index, end
        return None
    return None


def input_text(lines: list[Line], box: tuple[int, int]) -> str:
    first, end = box
    parts = [line.plain for line in lines[first:end]]
    parts[0] = parts[0].lstrip().removeprefix("❯")
    return snippet(" ".join(parts))


def _dialog_findings(tail: list[Line]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for kind, pattern in (("trust-dialog", _TRUST), ("usage-dialog", _USAGE), ("usage-dialog", _USAGE_TABS),
                          ("permission-prompt", _PERMISSION)):
        if any(seen == kind for seen, _ in found):
            continue
        for index, line in enumerate(tail):
            if pattern.search(line.text):
                text = line.text
                if kind == "usage-dialog":
                    used = [l.text for l in tail[index:] if "% used" in l.text]
                    text = " ".join([text] + used[:1])
                found.append((kind, snippet(text)))
                break
    if not found:
        for line in tail:
            if _ESC_CANCEL.search(line.text):
                found.append(("permission-prompt", snippet(line.text)))
                break
    return found


def _is_question(text: str) -> bool:
    if _NOT_A_QUESTION.search(text):
        return False
    return bool(_QUESTION_END.search(text) or _ASK_PHRASES.search(text))


def last_message_question(lines: list[Line]) -> str | None:
    """The question line of the last assistant message above the input box, if any.

    Without a ``⏺`` line in the read there is no message to judge.
    """
    start = None
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].stripped.startswith("⏺"):
            start = index
            break
    if start is None:
        return None
    message: list[str] = []
    for offset, line in enumerate(lines[start:]):
        stripped = line.stripped
        if offset and (stripped.startswith(_STATUS_PREFIXES) or _is_rule(line)):
            break
        if stripped:
            message.append(stripped.lstrip("⏺").strip())
    for text in reversed(message[-QUESTION_TAIL:]):
        if _is_question(text):
            return snippet(text)
    return None


def analyze(raw: str, agent_status: str | None = None) -> list[tuple[str, str]]:
    """Return (kind, snippet) pairs for one pane's ANSI output."""
    lines = parse_ansi(raw)
    box = find_input_box(lines)
    if box is None:
        tail = [line for line in lines if line.stripped][-DIALOG_TAIL:]
        return _dialog_findings(tail)
    found: list[tuple[str, str]] = []
    typed = input_text(lines, box)
    if typed:
        found.append(("input-text", typed))
    if agent_status != "working":
        top = box[0] - 1
        while top >= 0 and not _is_rule(lines[top]):
            top -= 1
        question = last_message_question(lines[:max(top, 0)])
        if question:
            found.append(("owner-question", question))
    return found


class Herdr:
    """Runs only the read-only herdr commands in READ_ONLY_COMMANDS."""

    def __init__(self, binary: str, timeout: float = 30.0):
        self.binary = binary
        self.timeout = timeout

    def _run(self, machine: str, args: list[str]) -> str:
        if tuple(args[:2]) not in READ_ONLY_COMMANDS:
            raise ValueError(f"refusing non-read-only herdr command {args[:2]}")
        cmd = [self.binary] + ([] if machine == LOCAL else ["--machine", machine]) + args
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=self.timeout)
        except FileNotFoundError as exc:
            raise RuntimeError(f"{self.binary!r} not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"herdr {' '.join(args[:2])} timed out") from exc
        if proc.returncode != 0:
            message = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(f"herdr {' '.join(args[:2])} exited {proc.returncode}"
                               + (f": {snippet(message[-1])}" if message else ""))
        return proc.stdout.decode("utf-8", "replace")

    def panes(self, machine: str) -> list[dict]:
        out = self._run(machine, ["pane", "list"])
        try:
            panes = json.loads(out)["result"]["panes"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("herdr pane list printed unexpected output") from exc
        if not isinstance(panes, list):
            raise RuntimeError("herdr pane list printed unexpected output")
        return [p for p in panes if isinstance(p, dict) and isinstance(p.get("pane_id"), str)]

    def read(self, machine: str, pane_id: str, lines: int) -> str:
        return self._run(machine, ["pane", "read", pane_id, "--format", "ansi", "--lines", str(lines)])


def scan(machines: list[str], herdr: Herdr, lines: int, local_name: str) -> ScanResult:
    result = ScanResult()
    for machine in machines:
        label = local_name if machine == LOCAL else machine
        try:
            panes = herdr.panes(machine)
        except RuntimeError as exc:
            result.errors.append(f"{label}\t-\terror\t{exc}")
            continue
        for pane in panes:
            pane_id = pane["pane_id"]
            if not pane.get("agent"):
                continue  # plain shell: its output is not an agent UI
            try:
                raw = herdr.read(machine, pane_id, lines)
            except RuntimeError as exc:
                result.errors.append(f"{label}\t{pane_id}\terror\t{exc}")
                continue
            for kind, text in analyze(raw, pane.get("agent_status")):
                result.findings.append(Finding(label, pane_id, kind, text))
    return result


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pane-watchdog",
        description="Read-only scan of herdr panes for open dialogs, waiting questions and typed input.",
    )
    parser.add_argument("machines", nargs="*", default=[LOCAL],
                        help=f"herdr machine labels or ids; '{LOCAL}' scans this machine (default)")
    parser.add_argument("--lines", type=int, default=DEFAULT_LINES, help="lines to read per pane")
    parser.add_argument("--local-name", default=socket.gethostname().split(".")[0] or LOCAL,
                        help="machine name printed for local panes (default: short hostname)")
    parser.add_argument("--json", action="store_true", help="print findings as a JSON list")
    args = parser.parse_args(argv)
    if args.lines < 1:
        parser.error("--lines must be positive")

    herdr = Herdr(os.environ.get("PANE_WATCHDOG_HERDR", "herdr"))
    result = scan(args.machines, herdr, args.lines, args.local_name)
    if args.json:
        print(json.dumps([f.__dict__ for f in result.findings], ensure_ascii=False))
    else:
        for finding in result.findings:
            print(finding.line())
    for error in result.errors:
        print(error, file=sys.stderr)
    if result.errors:
        return EXIT_ERROR
    return EXIT_FINDINGS if result.findings else EXIT_NONE
