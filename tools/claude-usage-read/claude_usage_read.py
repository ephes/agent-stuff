"""Read a Claude account's weekly usage without opening the /usage dialog.

``claude -p /usage --output-format json`` runs ``/usage`` as a local command:
no model call, no cost, no interactive dialog in a working pane. Its JSON
``result`` holds the same text the dialog shows, e.g.::

    Current week (all models): 3% used · resets Nov 12 at 7:59pm (Europe/Berlin)

This module runs that command for one Claude config dir, parses the
windows and prints one parseable line. ``--report`` hands the weekly windows
(all models, plus per-model ones such as Fable) to ``work usage report``.
Only the parsed windows are printed; the raw output (which also carries
account metadata such as the credential expiry) is never echoed. Python 3
stdlib only.

The default dir ``~/.claude`` is read with ``CLAUDE_CONFIG_DIR`` unset: Claude
Code keeps that dir's login in the keychain item ``Claude Code-credentials``,
but any explicit ``CLAUDE_CONFIG_DIR`` (even ``~/.claude``) makes it look for
``Claude Code-credentials-<hash>`` instead. Without a login it prints the
API-cost summary (``Estimated cost: ...``) rather than the usage windows.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

EXIT_OK = 0
EXIT_READ_FAILED = 1
EXIT_USAGE = 2
EXIT_REPORT_FAILED = 4

ALL_MODELS_LABEL = "week (all models)"
WORK_WINDOW = "Weekly · all models"
# Inherited variables that would make the child use another login, endpoint or
# pane: an API key or OAuth token overrides the config dir's subscription
# login, a session's CLAUDE_CODE_* settings or a herdr pane id would leak the
# caller's context into this read.
_SCRUBBED_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDECODE", "HERDR_")
SOURCE = "claude-usage-read"
DEFAULT_TIMEOUT = 60.0
WORK_TIMEOUT = 60.0

_WINDOW_LINE = re.compile(
    r"^\s*Current (?P<label>[^:]+?):\s*(?P<used>\d+(?:\.\d+)?)\s*%\s*used"
    r"(?:\s*·\s*resets\s+(?P<resets>.+?))?\s*$",
    re.IGNORECASE,
)
_RESET_TEXT = re.compile(
    r"^(?:(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?\s+at\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?"
    r"(?:\s*\((?P<tz>[^)]+)\))?$",
    re.IGNORECASE,
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class UsageError(Exception):
    """The usage could not be read or parsed. The message is safe to print."""


@dataclass
class Window:
    label: str
    used_percent: float
    resets_at: datetime | None

    @property
    def work_label(self) -> str | None:
        """The work app's label for a weekly window, None for any other window.

        ``week (all models)`` is ``Weekly · all models``, ``week (Fable)`` is
        ``Weekly · Fable``.
        """
        match = re.fullmatch(r"week\s*\((?P<scope>[^()]+)\)", self.label.strip(), re.IGNORECASE)
        if not match:
            return None
        scope = match["scope"].strip()
        return WORK_WINDOW if scope.lower() == "all models" else f"Weekly · {scope}"


def _zone(name: str | None, now: datetime) -> tzinfo:
    if not name:
        return now.astimezone().tzinfo
    if ZoneInfo is None:
        raise UsageError(f"cannot resolve time zone {name!r} (needs Python 3.9+)")
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UsageError(f"unknown time zone {name.strip()!r}") from exc


def parse_reset(text: str, now: datetime) -> datetime:
    """Turn ``Nov 12 at 7:59pm (Europe/Berlin)`` or ``8pm (UTC)`` into an aware datetime.

    The dialog leaves out the year: the reset is the first such moment no
    more than a day in the past (readings can lag the reset slightly).
    A bare time of day means today, or tomorrow once it has passed.
    """
    match = _RESET_TEXT.match(text.strip())
    if not match:
        raise UsageError(f"unrecognised reset time {text.strip()[:60]!r}")
    zone = _zone(match["tz"], now)
    local_now = now.astimezone(zone)
    hour = int(match["hour"])
    minute = int(match["minute"] or 0)
    ampm = (match["ampm"] or "").replace(".", "").lower()
    if ampm:
        if not 1 <= hour <= 12:
            raise UsageError(f"bad hour in reset time {text.strip()[:60]!r}")
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif match["minute"] is None or hour > 23:
        raise UsageError(f"unrecognised reset time {text.strip()[:60]!r}")
    if minute > 59:
        raise UsageError(f"bad minute in reset time {text.strip()[:60]!r}")

    if match["mon"] is None:
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < local_now:
            candidate = (candidate + timedelta(days=1)).replace(hour=hour, minute=minute)
        return candidate
    month = _MONTHS.get(match["mon"][:3].lower())
    if month is None:
        raise UsageError(f"unknown month in reset time {text.strip()[:60]!r}")
    day = int(match["day"])
    years = [int(match["year"])] if match["year"] else [local_now.year, local_now.year + 1]
    for year in years:
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=zone)
        except ValueError as exc:
            raise UsageError(f"invalid date in reset time {text.strip()[:60]!r}") from exc
        if match["year"] or candidate >= local_now - timedelta(days=1):
            return candidate
    return candidate


def parse_usage_text(text: str, now: datetime) -> list[Window]:
    windows = []
    for line in text.splitlines():
        match = _WINDOW_LINE.match(line)
        if not match:
            continue
        used = float(match["used"])
        if not 0 <= used <= 100:
            raise UsageError(f"percentage out of range in {line.strip()[:80]!r}")
        resets = parse_reset(match["resets"], now) if match["resets"] else None
        windows.append(Window(match["label"].strip(), used, resets))
    return windows


def parse_claude_output(stdout: str, now: datetime) -> list[Window]:
    """Parse the JSON of ``claude -p /usage --output-format json``."""
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise UsageError("claude did not print JSON") from exc
    if not isinstance(data, dict) or data.get("type") != "result":
        raise UsageError("claude printed no result object")
    result = data.get("result")
    if not isinstance(result, str):
        raise UsageError("claude result has no text")
    if data.get("is_error"):
        first = result.strip().splitlines()[0][:120] if result.strip() else "no message"
        raise UsageError(f"claude reported an error: {first}")
    if data.get("local_command") not in (None, "usage"):
        raise UsageError("claude did not run /usage as a local command")
    windows = parse_usage_text(result, now)
    if not windows:
        if re.search(r"^\s*(Estimated|Total) cost:", result, re.IGNORECASE | re.MULTILINE):
            raise UsageError("claude printed the API-cost summary, not usage windows: no "
                             "subscription login for this config dir (for ~/.claude, run without "
                             "CLAUDE_CONFIG_DIR; for another dir, log in with that dir)")
        raise UsageError("no 'Current ...: N% used' line in the /usage output "
                         "(not a subscription login, or the output format changed)")
    return windows


def weekly_all_models(windows: list[Window]) -> Window:
    for window in windows:
        if window.label.lower() == ALL_MODELS_LABEL:
            return window
    raise UsageError("no 'Current week (all models)' window in the /usage output")


def weekly_windows(windows: list[Window]) -> list[Window]:
    """The weekly windows ``--report`` sends, all-models first.

    A per-model line without its own reset time (a window not used this week)
    gets the all-models reset, the account's weekly cycle, so its earlier
    reading is still refreshed. The all-models window always has a reset
    (``main`` refuses to read without one).
    """
    weekly = sorted((w for w in windows if w.work_label), key=lambda w: w.work_label != WORK_WINDOW)
    cycle = next((w.resets_at for w in weekly if w.work_label == WORK_WINDOW), None)
    result = []
    for window in weekly:
        resets_at = window.resets_at or cycle
        if resets_at is not None:
            result.append(Window(window.label, window.used_percent, resets_at))
    return result


def default_config_dir(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def _is_default_dir(config_dir: Path) -> bool:
    try:
        return config_dir.expanduser().resolve() == (Path.home() / ".claude").resolve()
    except OSError:
        return False


def child_env(config_dir: Path, base=None) -> dict:
    """The environment for ``claude``: scrubbed, with the config dir selected.

    The default ``~/.claude`` runs with ``CLAUDE_CONFIG_DIR`` unset (see the
    module docstring); any other dir is passed explicitly.
    """
    base = os.environ if base is None else base
    env = {k: v for k, v in base.items()
           if k != "CLAUDE_CONFIG_DIR" and not k.startswith(_SCRUBBED_PREFIXES)}
    if not _is_default_dir(config_dir):
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


def run_claude(config_dir: Path, claude_bin: str, timeout: float) -> str:
    env = child_env(config_dir)
    cmd = [claude_bin, "-p", "/usage", "--output-format", "json", "--no-session-persistence"]
    try:
        proc = subprocess.run(
            cmd, env=env, cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise UsageError(f"{claude_bin!r} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise UsageError(f"claude did not answer within {timeout:g}s") from exc
    if proc.returncode != 0:
        raise UsageError(f"claude exited {proc.returncode}")
    return proc.stdout


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _number(value: float) -> str:
    return f"{value:g}"


def report_payload(windows: list[Window], observed_at: datetime, pool: str | None = None,
                   account: str | None = None) -> dict:
    """The ``work usage report --json -`` body for the weekly windows."""
    entries = []
    for window in weekly_windows(windows):
        entry = {"provider": "claude", "window_label": window.work_label,
                 "percent_used": window.used_percent, "resets_at": _iso(window.resets_at),
                 "observed_at": _iso(observed_at), "source": SOURCE}
        if pool:
            entry["pool"] = pool
        if account:
            entry["account"] = account
        entries.append(entry)
    return {"windows": entries}


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="claude-usage-read",
        description="Read a Claude account's weekly usage via `claude -p /usage` (no interactive dialog).",
    )
    parser.add_argument("config_dir", nargs="?",
                        help="Claude config dir (default: $CLAUDE_CONFIG_DIR, else ~/.claude)")
    parser.add_argument("--pool", help="work app pool slug for --report, e.g. claude-katharina")
    parser.add_argument("--account", help="work app account for --report (default: the pool's, else main)")
    parser.add_argument("--report", action="store_true",
                        help="also send the weekly windows to `work usage report`")
    parser.add_argument("--json", action="store_true", help="print all parsed windows as JSON")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds to wait for claude")
    args = parser.parse_args(argv)
    if (args.pool or args.account) and not args.report:
        parser.error("--pool and --account only apply with --report")

    config_dir = Path(args.config_dir).expanduser() if args.config_dir else default_config_dir()
    claude_bin = os.environ.get("CLAUDE_USAGE_READ_CLAUDE", "claude")
    work_bin = os.environ.get("CLAUDE_USAGE_READ_WORK", "work")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        windows = parse_claude_output(run_claude(config_dir, claude_bin, args.timeout), now)
        weekly = weekly_all_models(windows)
        if weekly.resets_at is None:
            raise UsageError("the weekly all-models window has no reset time")
    except UsageError as exc:
        print(f"claude-usage-read: {exc}", file=sys.stderr)
        return EXIT_READ_FAILED

    if args.json:
        print(json.dumps({
            "config_dir": str(config_dir),
            "observed_at": _iso(now),
            "used_percent": weekly.used_percent,
            "resets_at": _iso(weekly.resets_at),
            "windows": [{"label": w.label, "work_label": w.work_label, "used_percent": w.used_percent,
                         "resets_at": _iso(w.resets_at)} for w in windows],
        }, ensure_ascii=False))
    else:
        print(f"used={_number(weekly.used_percent)} resets_at={_iso(weekly.resets_at)} "
              f"observed_at={_iso(now)} config_dir={config_dir}")

    if args.report:
        payload = json.dumps(report_payload(windows, now, args.pool, args.account), ensure_ascii=False)
        try:
            proc = subprocess.run([work_bin, "usage", "report", "--json", "-"], input=payload, text=True,
                                  timeout=WORK_TIMEOUT)
        except FileNotFoundError:
            print(f"claude-usage-read: {work_bin!r} not found", file=sys.stderr)
            return EXIT_REPORT_FAILED
        except subprocess.TimeoutExpired:
            print(f"claude-usage-read: work usage report did not finish within {WORK_TIMEOUT:g}s",
                  file=sys.stderr)
            return EXIT_REPORT_FAILED
        if proc.returncode != 0:
            print(f"claude-usage-read: work usage report exited {proc.returncode}", file=sys.stderr)
            return EXIT_REPORT_FAILED
    return EXIT_OK
