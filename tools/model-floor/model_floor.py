"""Find OpenAI model ids below the GPT-6.2 floor in active configuration.

Owner rule (2026-11-18): no OpenAI model older than 6.2 is used anywhere in
the agent tooling. This scanner reports every numbered GPT id older than
`MIN_GPT_VERSION` (`gpt-6.1-sol`, `GPT-6 Sol`, `gpt-5.6-terra`, `gpt-4o`, ...)  # model-floor: allow
in the files it is given, except where history is the point:

- history paths: `CHANGELOG*`, `docs/archive/`, `docs/plans/`, `docs/specs/`
  and `docs/review-cycle-log.md` (dated records of what ran then), plus any
  glob listed in a `.model-floor-allow` file at the scanned root;
- a line that carries the marker `model-floor: allow` (a test fixture that
  proves an old id is refused);
- a file whose first five lines carry `model-floor: allow-file`.

At the top of a git checkout only tracked and new, not ignored files are
scanned (`git ls-files --cached --others --exclude-standard`); elsewhere the
whole tree is walked.

Unnumbered ids (`gpt-daybreak-blue-latest`, `codex-auto-review`) carry no
generation and are not reported. Exit 0 when clean, 1 with one line per
finding, 2 on a usage or Git enumeration error.
"""
import argparse
import fnmatch
import os
import re
import stat
import subprocess
import sys
from unicodedata import decimal

MIN_GPT_VERSION = (6, 2)
ALLOW_LINE = "model-floor: allow"
ALLOW_FILE = "model-floor: allow-file"
ALLOW_FILE_NAME = ".model-floor-allow"
DEFAULT_HISTORY = (
    "CHANGELOG*", "*/CHANGELOG*",
    "docs/archive/*", "docs/plans/*", "docs/specs/*",
    "docs/review-cycle-log.md",
)
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tox",
             ".mypy_cache", ".pytest_cache", ".ruff_cache"}
MAX_BYTES = 2_000_000

# `gpt-6.1-sol`, `GPT-6 Sol`, `openai/gpt-5.6`, `gpt-4o`: "gpt-" and a major  # model-floor: allow
# version, an optional ".minor", and no further digit or dot-digit after it.
_ID_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])gpt-(\d+)(?:\.(\d+))?(?![\d]|\.\d)")


def _component_key(digits):
    """Order decimal components by significant length, then by digit value."""
    if not digits.isascii():
        digits = "".join(str(decimal(digit)) for digit in digits)
    digits = digits.lstrip("0")
    return len(digits), digits


_FLOOR_KEY = tuple(_component_key(str(part)) for part in MIN_GPT_VERSION)


def _match_below_floor(match):
    major, minor = match.groups(default="0")
    return (_component_key(major), _component_key(minor)) < _FLOOR_KEY


def below_floor(model_id):
    match = _ID_RE.match(str(model_id).rsplit("/", 1)[-1])
    return match is not None and _match_below_floor(match)


def old_ids(line):
    """Every id in `line` that is below the floor, in order."""
    found = []
    for m in _ID_RE.finditer(line):
        if _match_below_floor(m):
            found.append(m.group(0))
    return found


def load_allow_globs(root):
    globs = list(DEFAULT_HISTORY)
    path = os.path.join(root, ALLOW_FILE_NAME)
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.split("#", 1)[0].strip()
                if line:
                    globs.append(line)
    except FileNotFoundError:
        pass
    return globs


def is_allowed_path(rel, globs):
    rel = rel.replace(os.sep, "/")
    return any(fnmatch.fnmatchcase(rel, g) for g in globs)


def _open_nonblocking(path, flags):
    return os.open(path, flags | getattr(os, "O_NONBLOCK", 0))


def scan_file(path):
    """Findings `(line_number, id, line)` in one text file."""
    data = bytearray()
    try:
        with open(path, "rb", buffering=0, opener=_open_nonblocking) as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                return []
            while len(data) <= MAX_BYTES:
                chunk = fh.read(MAX_BYTES + 1 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
    except OSError:
        return []
    if len(data) > MAX_BYTES or b"\0" in data[:8192]:
        return []
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if any(ALLOW_FILE in line for line in lines[:5]):
        return []
    findings = []
    for number, line in enumerate(lines, 1):
        if ALLOW_LINE in line:
            continue
        for model_id in old_ids(line):
            findings.append((number, model_id, line.strip()))
    return findings


class GitEnumerationError(RuntimeError):
    """Git could not enumerate files for a checkout."""


def git_files(root):
    """Tracked and new (not ignored) files, or None if there is no .git entry."""
    try:
        os.lstat(os.path.join(root, ".git"))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise GitEnumerationError(f"cannot inspect .git: {exc.strerror}") from exc
    try:
        proc = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        raise GitEnumerationError("git ls-files timed out") from exc
    except OSError as exc:
        raise GitEnumerationError(f"cannot run git ls-files: {exc.strerror}") from exc
    if proc.returncode != 0:
        raise GitEnumerationError(f"git ls-files failed (exit {proc.returncode})")
    names = sorted({os.fsdecode(n) for n in proc.stdout.split(b"\0") if n})
    return [os.path.join(root, n) for n in names]


def iter_files(root):
    tracked = git_files(root)
    if tracked is not None:
        yield from tracked
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def scan(root, extra_allow=()):
    """Findings `(relative_path, line_number, id, line)` under `root`."""
    root = os.path.abspath(root)
    globs = load_allow_globs(root) + list(extra_allow)
    findings = []
    for path in iter_files(root):
        rel = os.path.relpath(path, root)
        if is_allowed_path(rel, globs):
            continue
        for number, model_id, line in scan_file(path):
            findings.append((rel, number, model_id, line))
    return findings


def _display_path(path):
    """Keep a diagnostic on one line and escape undecodable filename bytes.

    A backslash is doubled only where it can be part of a filename; on
    Windows it is the path separator and stays as written.
    """
    if os.sep != "\\":
        path = path.replace("\\", "\\\\")
    return "".join(char if char.isprintable() else ascii(char)[1:-1]
                   for char in path)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="model-floor-check",
        description="Report OpenAI model ids below GPT-6.2 outside history.")
    p.add_argument("paths", nargs="+",
                   help="directories (scanned recursively) or single files")
    p.add_argument("--allow", action="append", default=[], metavar="GLOB",
                   help="extra path glob (relative to a scanned directory) "
                        "treated as history; repeatable")
    args = p.parse_args(argv)
    total = 0
    for target in args.paths:
        if os.path.isdir(target):
            try:
                hits = [(os.path.join(target, rel), n, m, line)
                        for rel, n, m, line in scan(target, args.allow)]
            except GitEnumerationError as exc:
                print(f"model-floor-check: {_display_path(target)}: {exc}", file=sys.stderr)
                return 2
        elif os.path.isfile(target):
            hits = [(target, n, m, line) for n, m, line in scan_file(target)]
        else:
            print(f"model-floor-check: no such file or directory: {_display_path(target)}",
                  file=sys.stderr)
            return 2
        for path, number, model_id, line in hits:
            print(f"{_display_path(path)}:{number}: {model_id}: {line[:200]}")
        total += len(hits)
    if total:
        print(f"model-floor-check: {total} id(s) below GPT-6.2", file=sys.stderr)
        return 1
    return 0
