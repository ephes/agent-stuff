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

``/usage`` leaves the windows out, and prints only "What's contributing to
your usage?", when its fetch of ``/api/oauth/usage`` fails, e.g. with HTTP 429
once many sessions of one login poll it. The read then runs with
``--debug-file`` in a private temp dir; only the fetch's HTTP status and retry
delay are taken from that log (never echoed), to name the reason. It then
falls back to Claude Code's own cached reading (``cachedUsageUtilization`` in
the config dir's ``.claude.json``, refreshed by every session of that login)
and reports it with its real fetch time as ``observed_at``, so it ages into
*stale* in the work app; exit 3 says so.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import fcntl
import hashlib
import tempfile
from contextlib import contextmanager
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
EXIT_STALE = 3
EXIT_REPORT_FAILED = 4

ALL_MODELS_LABEL = "week (all models)"
WORK_WINDOW = "Weekly · all models"
# Inherited variables that would make the child use another login, endpoint or
# pane: an API key or OAuth token overrides the config dir's subscription
# login, a session's CLAUDE_CODE_* settings or a herdr pane id would leak the
# caller's context into this read.
_SCRUBBED_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDECODE", "HERDR_")
SOURCE = "claude-usage-read"
CACHE_SOURCE = "claude-usage-read:cache"
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


class WindowsMissing(UsageError):
    """/usage ran with a subscription login but printed no usage windows."""


@dataclass
class FetchDiagnostics:
    """What claude's debug log says about its ``/api/oauth/usage`` fetch.

    Only these fields are taken from the log; nothing else of it is kept.
    """
    attempted: bool = False
    failed: bool = False
    status: int | None = None
    retry_after_s: int | None = None


_DEBUG_ATTEMPT = re.compile(r"fetchUtilization: GET /api/oauth/usage")
_DEBUG_FAILED = re.compile(r"Failed to load usage data(?:: .*?status code (?P<status>\d{3}))?")
_DEBUG_REMEMBERED = re.compile(r"fetchUtilization: (?P<status>\d{3}) remembered.*?not asking again for "
                               r"(?P<secs>\d+)\s*s")


def parse_debug_log(text: str) -> FetchDiagnostics:
    diag = FetchDiagnostics()
    for line in text.splitlines():
        if _DEBUG_ATTEMPT.search(line):
            diag.attempted = True
        match = _DEBUG_REMEMBERED.search(line)
        if match:
            diag.attempted = True
            diag.failed = True
            diag.status = int(match["status"])
            diag.retry_after_s = int(match["secs"])
            continue
        match = _DEBUG_FAILED.search(line)
        if match:
            diag.failed = True
            if match["status"]:
                diag.status = int(match["status"])
    return diag


def missing_windows_reason(diag: FetchDiagnostics | None, config_dir: Path | None = None) -> str:
    """A precise, printable reason for a /usage output without windows."""
    prefix = "windows section missing"
    if diag is None or not (diag.attempted or diag.failed):
        return (f"{prefix} - no usage fetch in claude's debug log (the output format or the "
                "debug log changed)")
    if diag.status == 429:
        wait = f"; Claude Code will not ask again for ~{-(-diag.retry_after_s // 60)} min" \
            if diag.retry_after_s else ""
        return (f"{prefix} - usage fetch rate-limited (HTTP 429: too many /api/oauth/usage "
                f"requests for this login{wait})")
    if diag.status in (401, 403):
        login = "claude" if config_dir is None or _is_default_dir(config_dir) \
            else f"CLAUDE_CONFIG_DIR={config_dir} claude"
        return (f"{prefix} - login lacks usage scope or was revoked (HTTP {diag.status}); "
                f"log in again: {login}, then /login")
    if diag.failed:
        status = f" (HTTP {diag.status})" if diag.status else ""
        return f"{prefix} - usage fetch failed{status}"
    return f"{prefix} - the usage fetch ran but returned no windows"


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


def parse_claude_output(stdout: str, now: datetime, diag: FetchDiagnostics | None = None,
                        config_dir: Path | None = None) -> list[Window]:
    """Parse the JSON of ``claude -p /usage --output-format json``.

    ``diag`` (from claude's debug log) names the reason when the windows are
    missing; such a failure is a ``WindowsMissing``.
    """
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
        if diag is not None and (diag.attempted or diag.failed):
            raise WindowsMissing(missing_windows_reason(diag, config_dir))
        if re.search(r"using your subscription|contributing to your usage", result, re.IGNORECASE):
            raise WindowsMissing(missing_windows_reason(diag, config_dir))
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
    default = Path.home() / ".claude"
    # Lexically first, as Claude Code joins the dir: "link/../x" is "x", whatever link points to.
    spelled = Path(os.path.normpath(str(config_dir.expanduser())))
    try:
        if spelled.resolve() == default.resolve():
            return True
        # Also a differently cased spelling on a case-insensitive volume.
        return os.path.samefile(spelled, default)
    except (OSError, RuntimeError, ValueError):
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


def run_claude(config_dir: Path, claude_bin: str, timeout: float) -> tuple[str, FetchDiagnostics | None]:
    """Run ``claude -p /usage`` for ``config_dir``; return its stdout and fetch diagnostics.

    The debug log goes to a private temp dir that is removed afterwards; only
    ``parse_debug_log``'s fields are taken from it. ``None`` when no log came.
    """
    env = child_env(config_dir)
    with tempfile.TemporaryDirectory(prefix="claude-usage-read.") as tmp:
        debug_file = Path(tmp) / "debug.log"
        cmd = [claude_bin, "-p", "/usage", "--output-format", "json", "--no-session-persistence",
               "--debug-file", str(debug_file)]
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
        try:
            diag = parse_debug_log(debug_file.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            diag = None
    return proc.stdout, diag


def claude_json_path(config_dir: Path) -> Path:
    """Where Claude Code keeps the dir's state (``~/.claude.json`` for the default dir).

    Joined like Claude Code's own ``path.join``: lexically normalized, so
    ``link/../cfg`` names the same file for it and for this fallback.
    """
    if _is_default_dir(config_dir):
        return Path.home() / ".claude.json"
    return Path(os.path.normpath(os.path.join(str(config_dir.expanduser()), ".claude.json")))


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _cache_window(limit) -> Window | None:
    if not isinstance(limit, dict) or limit.get("group") != "weekly":
        return None
    percent = limit.get("percent")
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 <= percent <= 100:
        return None
    if limit.get("kind") == "weekly_all":
        label = ALL_MODELS_LABEL
    elif limit.get("kind") == "weekly_scoped":
        scope = limit.get("scope") if isinstance(limit.get("scope"), dict) else {}
        model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
        name = model.get("display_name")
        if not isinstance(name, str) or not name.strip() or "(" in name or ")" in name:
            return None
        label = f"week ({name.strip()})"
    else:
        return None
    resets_at = _parse_iso(limit.get("resets_at"))
    return Window(label, float(percent), resets_at.replace(microsecond=0) if resets_at else None)


def read_cached_usage(config_dir: Path, now: datetime) -> tuple[list[Window], datetime, str]:
    """Claude Code's own last reading: ``cachedUsageUtilization`` in ``.claude.json``.

    Every session of the login refreshes it, so it can be newer than this
    tool's last successful read. Returns the weekly windows and the fetch
    time and the account id. Only that key and the account id are looked at;
    nothing else of the file is kept or printed.
    """
    path = claude_json_path(config_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UsageError(f"no {path.name} in the config dir") from exc
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read {path.name}") from exc
    cache = data.get("cachedUsageUtilization") if isinstance(data, dict) else None
    if not isinstance(cache, dict):
        raise UsageError("Claude Code has no cached usage reading")
    account = data.get("oauthAccount") if isinstance(data.get("oauthAccount"), dict) else {}
    if not account.get("accountUuid") or cache.get("accountUuid") != account.get("accountUuid"):
        raise UsageError("the cached usage reading belongs to another account")
    fetched_ms = cache.get("fetchedAtMs")
    if isinstance(fetched_ms, bool) or not isinstance(fetched_ms, (int, float)):
        raise UsageError("the cached usage reading has no fetch time")
    try:
        fetched_at = datetime.fromtimestamp(fetched_ms / 1000, timezone.utc).replace(microsecond=0)
    except (OverflowError, OSError, ValueError) as exc:
        raise UsageError("the cached usage reading has an invalid fetch time") from exc
    if fetched_at > now + timedelta(minutes=5):
        raise UsageError("the cached usage reading is dated in the future")
    utilization = cache.get("utilization") if isinstance(cache.get("utilization"), dict) else {}
    limits = utilization.get("limits")
    windows = [w for w in map(_cache_window, limits if isinstance(limits, list) else []) if w]
    if not any(w.label == ALL_MODELS_LABEL for w in windows):
        seven_day = utilization.get("seven_day") if isinstance(utilization.get("seven_day"), dict) else {}
        window = _cache_window({"group": "weekly", "kind": "weekly_all",
                                "percent": seven_day.get("utilization"),
                                "resets_at": seven_day.get("resets_at")})
        if window:
            windows.insert(0, window)
    weekly = next((w for w in windows if w.label == ALL_MODELS_LABEL), None)
    if weekly is None or weekly.resets_at is None:
        raise UsageError("the cached usage reading has no weekly all-models window")
    if weekly.resets_at <= now:
        raise UsageError(f"the cached usage reading (fetched {_iso(fetched_at)}) predates the "
                         "weekly reset")
    # A per-model window whose own reset has passed is a reading of an earlier cycle.
    return [w for w in windows if w.resets_at is None or w.resets_at > now], fetched_at, account["accountUuid"]


def state_file(config_dir: Path, pool: str | None = None, account: str | None = None, env=None) -> Path:
    """Record of the newest cached ``observed_at`` this tool reported for one profile path and target.

    Keyed by the ``.claude.json`` path Claude Code reads for the dir plus
    ``--pool``/``--account`` as given. Only cached readings are recorded, with
    the account id read together with that cache, and the record only holds
    back a cached reading of the same account, so one login never suppresses
    another's. Aliases (a symlink, implicit vs explicit default account) are
    separate records, and a cached reading older than a live report is still
    sent once: at worst a duplicate or older snapshot, which the append-only
    work app orders by ``observed_at``.
    """
    env = os.environ if env is None else env
    base = Path(env.get("CLAUDE_USAGE_READ_STATE") or Path.home() / ".local" / "state" / "claude-usage-read")
    ident = "\0".join([str(claude_json_path(config_dir)), pool or "", account or ""])
    key = hashlib.sha256(ident.encode()).hexdigest()[:16]
    return base.expanduser() / f"{key}.json"


@contextmanager
def report_lock(path: Path):
    """Serialize check, report and record per config dir (best effort without a lock file)."""
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path.with_suffix(".lock"), "a")
        fcntl.flock(handle, fcntl.LOCK_EX)
    except OSError:
        if handle is not None:
            handle.close()
        handle = None
    try:
        yield
    finally:
        if handle is not None:
            handle.close()


def last_reported(path: Path, account: str | None) -> datetime | None:
    """The recorded ``observed_at``, only when it was recorded for this account."""
    if not account:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("account_uuid") != account:
        return None
    return _parse_iso(data.get("observed_at"))


def remember_reported(path: Path, observed_at: datetime, account: str | None) -> None:
    """Best effort: a lost record only means a cached reading may be sent again."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"observed_at": _iso(observed_at), "account_uuid": account}) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _number(value: float) -> str:
    return f"{value:g}"


def report_payload(windows: list[Window], observed_at: datetime, pool: str | None = None,
                   account: str | None = None, source: str = SOURCE) -> dict:
    """The ``work usage report --json -`` body for the weekly windows."""
    entries = []
    for window in weekly_windows(windows):
        entry = {"provider": "claude", "window_label": window.work_label,
                 "percent_used": window.used_percent, "resets_at": _iso(window.resets_at),
                 "observed_at": _iso(observed_at), "source": source}
        if pool:
            entry["pool"] = pool
        if account:
            entry["account"] = account
        entries.append(entry)
    return {"windows": entries}


def _report(windows, observed_at, stale, record, args, work_bin, account=None) -> int:
    """Send the windows to ``work usage report`` unless a stale reading is not newer than the last one."""
    if stale:
        # Checked again under the lock: a reset may have passed while this run waited for it.
        now = datetime.now(timezone.utc)
        windows = [w for w in windows if w.resets_at is None or w.resets_at > now]
        if not any(w.label.lower() == ALL_MODELS_LABEL for w in windows):
            print("claude-usage-read: the cached usage reading expired at the weekly reset before it "
                  "could be reported; nothing reported", file=sys.stderr)
            return EXIT_READ_FAILED
    previous = last_reported(record, account)
    if stale and previous is not None and observed_at <= previous:
        print(f"claude-usage-read: cached reading from {_iso(observed_at)} is not newer than the last "
              f"cached reading reported ({_iso(previous)}); nothing reported", file=sys.stderr)
        return EXIT_OK
    payload = json.dumps(report_payload(windows, observed_at, args.pool, args.account,
                                        CACHE_SOURCE if stale else SOURCE), ensure_ascii=False)
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
    # Only cached readings are recorded, under the account id read with that very cache.
    if stale and account and (previous is None or observed_at > previous):
        remember_reported(record, observed_at, account)
    return EXIT_OK


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
    # claude runs in the temp dir: a relative dir must name the same place for it and the fallback.
    # Prefixed, not resolved: the keychain item claude looks up depends on the dir's spelling.
    if not config_dir.is_absolute():
        config_dir = Path.cwd() / config_dir
    claude_bin = os.environ.get("CLAUDE_USAGE_READ_CLAUDE", "claude")
    work_bin = os.environ.get("CLAUDE_USAGE_READ_WORK", "work")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    observed_at = now
    reason = None
    login = None
    try:
        stdout, diag = run_claude(config_dir, claude_bin, args.timeout)
        try:
            windows = parse_claude_output(stdout, now, diag, config_dir)
        except WindowsMissing as exc:
            reason = str(exc)
            try:
                # Sampled again: claude may have run across the weekly reset.
                windows, observed_at, login = read_cached_usage(
                    config_dir, datetime.now(timezone.utc).replace(microsecond=0))
            except UsageError as cache_exc:
                raise UsageError(f"{reason}; no usable cached reading: {cache_exc}") from cache_exc
            print(f"claude-usage-read: {reason}; using Claude Code's cached reading from "
                  f"{_iso(observed_at)} (stale)", file=sys.stderr)
        weekly = weekly_all_models(windows)
        if weekly.resets_at is None:
            raise UsageError("the weekly all-models window has no reset time")
    except UsageError as exc:
        print(f"claude-usage-read: {exc}", file=sys.stderr)
        return EXIT_READ_FAILED
    stale = reason is not None

    if args.json:
        print(json.dumps({
            "config_dir": str(config_dir),
            "observed_at": _iso(observed_at),
            "stale": stale,
            "reason": reason,
            "used_percent": weekly.used_percent,
            "resets_at": _iso(weekly.resets_at),
            "windows": [{"label": w.label, "work_label": w.work_label, "used_percent": w.used_percent,
                         "resets_at": _iso(w.resets_at)} for w in windows],
        }, ensure_ascii=False))
    else:
        print(f"used={_number(weekly.used_percent)} resets_at={_iso(weekly.resets_at)} "
              f"observed_at={_iso(observed_at)} config_dir={config_dir}" + (" stale=cached" if stale else ""))

    done = EXIT_STALE if stale else EXIT_OK
    if args.report:
        record = state_file(config_dir, args.pool, args.account)
        with report_lock(record):
            code = _report(windows, observed_at, stale, record, args, work_bin, login)
        if code != EXIT_OK:
            return code
    return done
