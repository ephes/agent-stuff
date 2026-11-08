"""Refuse Codex work while the Codex subscription limit is used up.

Codex does not stop at 100 % of its weekly window when the account has paid
credits: the call simply runs and spends credits. This module reads the newest
rate-limit reading from Codex's own session records (``~/.codex/sessions``,
the same source as ``work usage collect-codex``) and reports a block while a
window is at or above the limit and has not reset yet.

Only the rate-limit windows and the event timestamp are read; no session
content and no credit balance is returned. Python 3 stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ALLOW_ENV = "CODEX_QUOTA_ALLOW_CREDITS"
MAX_PERCENT_ENV = "CODEX_QUOTA_MAX_PERCENT"
DEFAULT_MAX_PERCENT = 100.0
MAX_SESSION_FILES = 20
MAX_RECORD_BYTES = 1024 * 1024
EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_USAGE = 2


@dataclass
class Window:
    label: str
    used_percent: float
    resets_at: datetime


@dataclass
class Status:
    blocked: bool
    message: str
    observed_at: datetime | None = None
    windows: list[Window] = field(default_factory=list)


def codex_home(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def _label(minutes: int) -> str:
    return {10080: "weekly", 300: "5-hour"}.get(minutes, f"{minutes}-minute")


def _timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _window(raw) -> Window | None:
    if not isinstance(raw, dict):
        return None
    used, minutes, resets = raw.get("used_percent"), raw.get("window_minutes"), raw.get("resets_at")
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
        return None
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        return None
    if isinstance(resets, bool) or not isinstance(resets, (int, float)):
        return None
    try:
        reset_time = datetime.fromtimestamp(resets, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return Window(_label(minutes), float(used), reset_time)


def _reading(path: Path) -> tuple[datetime, list[Window]] | None:
    """Newest event timestamp; equal-time observations keep the first record."""
    found = None
    with path.open("rb") as handle:
        while True:
            raw = handle.readline(MAX_RECORD_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_RECORD_BYTES:
                while raw and not raw.endswith(b"\n"):
                    raw = handle.readline(MAX_RECORD_BYTES + 1)
                continue
            if b"rate_limits" not in raw:
                continue
            line = raw.decode("utf-8", errors="replace")
            if "rate_limits" not in line:
                continue
            try:
                event = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(event, dict):
                continue
            payload = event.get("payload")
            limits = None
            for holder in (payload, event):
                if isinstance(holder, dict) and isinstance(holder.get("rate_limits"), dict):
                    limits = holder["rate_limits"]
                    break
            observed = _timestamp(event.get("timestamp"))
            if limits is None or observed is None:
                continue
            windows = [w for w in (_window(limits.get(k)) for k in ("primary", "secondary")) if w]
            if windows and (found is None or observed > found[0]):
                found = (observed, windows)
    return found


def latest_reading(home: Path) -> tuple[datetime, list[Window]] | None:
    """The freshest reading across the newest session records, or None."""
    stamped = []
    for path in (home / "sessions").glob("**/rollout-*.jsonl"):
        try:
            if path.is_file():
                stamped.append((path.stat().st_mtime, path.name, path))
        except OSError:
            continue
    stamped.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = None
    for _, _, path in stamped[:MAX_SESSION_FILES]:
        try:
            reading = _reading(path)
        except OSError:
            continue
        if reading and (best is None or reading[0] > best[0]):
            best = reading
    return best


def _max_percent(env) -> float:
    raw = env.get(MAX_PERCENT_ENV)
    if raw in (None, ""):
        return DEFAULT_MAX_PERCENT
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{MAX_PERCENT_ENV} must be a number, not {raw!r}") from None
    if not 0 < value <= 100:
        raise ValueError(f"{MAX_PERCENT_ENV} must be in (0, 100], not {raw!r}")
    return value


def _fmt(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def check(home: Path | None = None, now: datetime | None = None, env=None) -> Status:
    """Return whether Codex work should be refused now."""
    env = os.environ if env is None else env
    home = codex_home(env) if home is None else home
    now = datetime.now(timezone.utc) if now is None else now
    max_percent = _max_percent(env)
    reading = latest_reading(home)
    if reading is None:
        return Status(False, f"no Codex rate-limit reading under {home / 'sessions'}; not checked")
    observed, windows = reading
    full = [w for w in windows if w.used_percent >= max_percent and w.resets_at > now]
    if not full:
        parts = ", ".join(f"{w.label} {w.used_percent:g}%" for w in windows)
        return Status(False, f"Codex limits OK ({parts}; reading from {_fmt(observed)})", observed, windows)
    w = max(full, key=lambda item: item.resets_at)
    message = (
        f"Codex {w.label} limit is at {w.used_percent:g}% until {_fmt(w.resets_at)} "
        f"(reading from {_fmt(observed)}); a Codex run now would spend paid credits."
    )
    if env.get(ALLOW_ENV) == "1":
        return Status(False, message + f" Allowed by {ALLOW_ENV}=1.", observed, windows)
    return Status(True, message + f" Set {ALLOW_ENV}=1 to run anyway.", observed, windows)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="codex-quota-guard",
        description="Exit 3 while the Codex subscription limit is used up (Codex would spend paid credits).",
    )
    parser.add_argument("--json", action="store_true", help="print the status as JSON")
    parser.add_argument("--quiet", action="store_true", help="print only when blocked")
    args = parser.parse_args(argv)
    try:
        status = check()
    except ValueError as exc:
        print(f"codex-quota-guard: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        print(json.dumps({
            "blocked": status.blocked,
            "message": status.message,
            "observed_at": status.observed_at.isoformat() if status.observed_at else None,
            "windows": [
                {"label": w.label, "used_percent": w.used_percent, "resets_at": w.resets_at.isoformat()}
                for w in status.windows
            ],
        }))
    elif status.blocked:
        print(f"codex-quota-guard: {status.message}", file=sys.stderr)
    elif not args.quiet:
        print(f"codex-quota-guard: {status.message}")
    return EXIT_BLOCKED if status.blocked else EXIT_OK
