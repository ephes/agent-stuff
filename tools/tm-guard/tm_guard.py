"""tm-guard: a never-blocking Time Machine stall probe for the Studio, reported to Nyxmon through macmini.

On 2026-11-19 the Studio's Time Machine run stalled for 16 hours while
``tmutil status`` kept showing ``ThinningPostBackup``; at the end ``tmutil``
itself hung (ops-control ``runbooks/time-machine-client-stall.md``). Every
five minutes (LaunchAgent ``de.wersdoerfer.tm-guard``) this probe records:

- whether ``tmutil status -X`` answers within ``TMUTIL_TIMEOUT`` seconds. It
  runs in a child that is killed (SIGKILL to that child's own PID, nothing
  else) when the time is up; a killed child that still has not exited is
  remembered (``hung.json``, PID plus its start time from ``ps``), and while
  it lives no further ``tmutil`` is started: the report says ``hung``;
- phase and progress (``BackupPhase``, ``Percent``, bytes and files done and
  planned, ``DateOfStateChange``) and ``defaults read
  /Library/Preferences/com.apple.TimeMachine AutoBackup`` (``auto_backup``:
  off is a normal state, reported for information only);
- the newest write into the bundle's ``bands/`` and ``mapped/`` on the backup
  server, read-only over SSH (``find -printf``), as the runbook does it: a
  thinning or deletion phase shows no byte counter but writes bands;
- ``stalled_seconds``: how long a running backup went without any progress
  (a change of phase, counters, percent or state-change date, or a newer band
  write). 0 when no backup runs.

The report goes to macmini as root over SSH (``obs_ctl.py timemachine``);
the status endpoint there feeds Nyxmon's "Studio Time Machine progress" check
(ops-control ``docs/OBSERVABILITY_ROUTINE.md``). Every external command has a
hard time limit; the probe never touches the backup volume itself.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
import plistlib
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

TMUTIL_TIMEOUT = 120  # the runbook's "tmutil does not return within 2 minutes" is the stalled state
DEFAULTS_TIMEOUT = 20
PS_TIMEOUT = 10
BAND_TIMEOUT = 60
REPORT_TIMEOUT = 100  # obs_ctl.py waits up to 60 s for its lock plus 20 s for the write
KILL_GRACE = 5.0  # after SIGKILL: how long the child gets to be reaped before it counts as hung
MAX_OUTPUT = 1024 * 1024
MAX_STATE_BYTES = 64 * 1024
MAX_HUNG = 20
PHASE = re.compile(r"[^A-Za-z0-9_. -]")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+")
SAFE_HOST = re.compile(r"[A-Za-z0-9_.@-]+")
STATE_FORMAT = 1


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def state_dir() -> Path:
    return Path(env("TM_GUARD_STATE", str(Path.home() / ".local/state/tm-guard")))


def log(message: str) -> None:
    print(f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')} tm-guard: {message}", flush=True)


# -- bounded child processes -----------------------------------------------------------------------


@dataclass
class Outcome:
    """What a bounded child did: ``ok`` (exited, any code), ``timeout`` or ``error`` (could not start)."""

    status: str
    code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    pid: int | None = None
    reaped: bool = True

    def tail(self) -> str:
        text = (self.stderr or self.stdout).decode("utf-8", "replace").strip().replace("\n", " ")
        return text[-160:]


def bounded(
    argv: list[str],
    seconds: float,
    stdin: bytes | None = None,
    on_start: Callable[[int], None] | None = None,
    extra_env: dict[str, str] | None = None,
) -> Outcome:
    """Run ``argv`` for at most ``seconds``; then SIGKILL that child's PID (only it) and wait ``KILL_GRACE``.

    Never waits without a deadline: a child stuck in an uninterruptible wait
    (as ``tmutil`` was on 2026-11-19) is left behind unreaped (``reaped``
    False). ``on_start`` gets the child's PID as soon as it runs (``tmutil``
    is recorded then, so even a probe stopped mid-wait leaves its record);
    ``seconds`` count from its return, when the standard input (the gate's
    go line) is written.
    """

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            env={**os.environ, **extra_env} if extra_env else None,
            # Its own session: launchd's clean-up of this job's process group never reaches it;
            # only the SIGKILL below, to its own PID, does.
            start_new_session=True,
        )
    except OSError as error:
        return Outcome("error", stderr=str(error).encode())
    assert proc.stdout is not None and proc.stderr is not None
    if on_start is not None:
        try:
            on_start(proc.pid)  # its ps call has PS_TIMEOUT
        except OSError as error:
            if proc.stdin is not None:
                proc.stdin.close()  # EOF, with no go line
            with contextlib.suppress(ProcessLookupError):
                os.kill(proc.pid, signal.SIGKILL)
            reaped = _wait_until(proc, time.monotonic() + KILL_GRACE) is not None
            proc.stdout.close()
            proc.stderr.close()
            return Outcome("error", stderr=f"cannot record process ownership: {error}".encode(),
                           pid=proc.pid, reaped=reaped)
    deadline = time.monotonic() + seconds
    if stdin is not None:
        assert proc.stdin is not None
        try:
            # Small payloads only (well below a pipe buffer): this write does not block.
            proc.stdin.write(stdin)
            proc.stdin.close()
        except OSError:
            pass
    buffers = {proc.stdout.fileno(): bytearray(), proc.stderr.fileno(): bytearray()}
    out_fd, err_fd = proc.stdout.fileno(), proc.stderr.fileno()
    open_fds = set(buffers)
    while open_fds:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select(list(open_fds), [], [], remaining)
        for fd in ready:
            chunk = os.read(fd, 65536)
            if not chunk:
                open_fds.discard(fd)
            elif len(buffers[fd]) < MAX_OUTPUT:
                buffers[fd].extend(chunk[: MAX_OUTPUT - len(buffers[fd])])
    code = _wait_until(proc, deadline)
    if code is not None:
        proc.stdout.close()
        proc.stderr.close()
        return Outcome("ok", code, bytes(buffers[out_fd]), bytes(buffers[err_fd]), proc.pid)
    with contextlib.suppress(ProcessLookupError):
        os.kill(proc.pid, signal.SIGKILL)  # the child this call started, by its own PID
    reaped = _wait_until(proc, time.monotonic() + KILL_GRACE) is not None
    proc.stdout.close()
    proc.stderr.close()
    return Outcome("timeout", None, bytes(buffers[out_fd]), bytes(buffers[err_fd]), proc.pid, reaped=reaped)


def _wait_until(proc: subprocess.Popen[bytes], deadline: float) -> int | None:
    while True:
        code = proc.poll()
        if code is not None:
            return code
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


GONE = "<gone>"  # ps says the PID does not exist
UNKNOWN = "<unknown>"  # ps did not tell (timed out, failed to start, a diagnostic, an odd answer)
# The gate's accounting name before its exec: /bin/sh on macOS dispatches to bash (seen as "bash").
GATE_NAMES = ("sh", "bash", "zsh", "dash")
LSTART = re.compile(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2} \d{2}:\d{2}:\d{2} \d{4}")


def ps_lstart(pid: int) -> str:
    """``pid``'s start time as ``ps -o lstart=`` prints it, or ``GONE`` or ``UNKNOWN``.

    Printed in UTC (``TZ=UTC0``) and compared as text, never converted: the
    start time of a process stays the same for its whole life (an ``exec``
    keeps it), and a later process under a reused PID shows another one,
    whatever the wall clock or the local time zone does in between.
    """

    # UTC: the text must not depend on the time zone of whoever runs the probe.
    done = bounded([env("TM_GUARD_PS", "/bin/ps"), "-o", "lstart=", "-p", str(pid)], PS_TIMEOUT, extra_env={"TZ": "UTC0"})
    if done.status != "ok" or done.stderr:
        return UNKNOWN
    if done.code == 1 and not done.stdout:
        return GONE  # ps -p: exit 1, no line and no diagnostic for a PID that does not exist
    line = " ".join(done.stdout.decode("utf-8", "replace").split())
    if done.code != 0 or not LSTART.fullmatch(line):
        return UNKNOWN
    return line


def ps_name(pid: int) -> str:
    """``pid``'s accounting name (``ps -o ucomm=``: ``tmutil``, or e.g. ``bash`` for the gate), or ``GONE``/``UNKNOWN``.

    The two markers hold ``<``/``>``, which no accepted name does.
    """

    done = bounded([env("TM_GUARD_PS", "/bin/ps"), "-o", "ucomm=", "-p", str(pid)], PS_TIMEOUT)
    if done.status != "ok" or done.stderr:
        return UNKNOWN
    if done.code == 1 and not done.stdout:
        return GONE
    name = done.stdout.decode("utf-8", "replace").strip()
    if done.code != 0 or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,32}", name):
        return UNKNOWN
    return name


# -- state -----------------------------------------------------------------------------------------


def read_json(path: Path) -> Any:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
                return None
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(MAX_STATE_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_STATE_BYTES:
            return None
        return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None


def write_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def run_lock(state: Path) -> Iterator[bool]:
    path = state / "run.lock"
    try:
        state.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
    except OSError:
        yield False
        return
    try:
        try:
            opened = os.fstat(fd)
            held = False
            if stat.S_ISREG(opened.st_mode):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = os.path.samestat(opened, path.lstat())
        except OSError:
            held = False
        yield held
    finally:
        os.close(fd)


def still_hung(entries: Any) -> list[dict[str, Any]]:
    """The recorded ``tmutil`` children that may still live.

    With a recorded UTC start time (``lstart_utc``, ``ps_lstart`` taken
    before the child was let go): while its PID shows that same start time,
    or ``ps`` cannot tell. Without one (``ps`` failed then, the probe died in
    between, or an older record holds only a local-time ``lstart``): while
    the PID runs a ``tmutil`` or a shell (``GATE_NAMES``: the gate before its exec), or
    ``ps`` cannot tell; a positively different program under that PID is a
    reused PID.
    """

    alive: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return alive
    for entry in entries[:MAX_HUNG]:
        if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int):
            continue
        now = ps_lstart(entry["pid"])
        if now == GONE:
            continue
        recorded = entry.get("lstart_utc")  # an older local-time "lstart" counts as none
        if isinstance(recorded, str):
            if now in (UNKNOWN, recorded):
                alive.append(entry)
        elif ps_name(entry["pid"]) in (UNKNOWN, "tmutil", *GATE_NAMES):
            alive.append(entry)
    return alive


# -- probes ----------------------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _count(value: Any) -> int | None:
    if type(value) is int:
        return value if 0 <= value < 10**16 else None
    if isinstance(value, float):
        return int(value) if 0 <= value < 10**16 and value.is_integer() else None
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation:
            return None
        if number.is_finite() and 0 <= number < 10**16 and number == number.to_integral_value():
            return int(number)
    return None


def _flag(value: Any) -> bool | None:
    """A plist boolean or a legacy integer flag (0 or 1)."""

    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    return None


def parse_status(raw: bytes) -> dict[str, Any]:
    """The fields of ``tmutil status -X`` this probe reports; ``ValueError`` when it is not a plist dict."""

    try:
        data = plistlib.loads(raw)
    except Exception as error:  # noqa: BLE001 - plistlib raises several types
        raise ValueError(f"not a plist: {type(error).__name__}") from None
    if not isinstance(data, dict):
        raise ValueError("not a plist dictionary")
    progress = data.get("Progress") if isinstance(data.get("Progress"), dict) else {}

    def field(*names: str) -> Any:
        for name in names:
            for source in (progress, data):
                if name in source:
                    return source[name]
        return None

    percent = _number(data.get("Percent", progress.get("Percent")))
    if percent is not None and not 0 <= percent <= 100:
        percent = None  # -1: Time Machine does not know
    changed = data.get("DateOfStateChange")
    running = _flag(data.get("Running"))
    if running is None:
        raise ValueError("no readable Running field")
    return {
        "running": running,
        "stopping": bool(_flag(data.get("Stopping"))),
        "phase": PHASE.sub("_", str(data.get("BackupPhase") or ""))[:60],
        "percent": percent,
        "bytes": _count(field("bytes")),
        "files": _count(field("files")),
        "total_bytes": _count(field("totalBytes")),
        "total_files": _count(field("totalFiles")),
        "state_changed": changed.isoformat() if isinstance(changed, datetime) else str(changed or "")[:40],
    }


def _recorded_time(value: Any) -> str:
    if type(value) in (int, float):
        try:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
        except (OverflowError, OSError, ValueError):
            pass
    return "unknown time"


def read_tmutil(state: Path) -> tuple[str, str, dict[str, Any]]:
    """(``ok``/``timeout``/``hung``/``error``, detail, parsed fields)."""

    hung_path = state / "hung.json"
    recorded = read_json(hung_path)
    alive = still_hung(recorded)
    if recorded is not None and alive != recorded:
        write_atomic(hung_path, alive)
    if alive:
        first = alive[0]
        if "killed_at" in first:
            since = _recorded_time(first["killed_at"])
            return "hung", f"tmutil pid {first['pid']} killed at {since} has not exited", {}
        since = _recorded_time(first.get("started_at"))
        return "hung", f"tmutil pid {first['pid']} started at {since} by an earlier probe has not exited", {}
    entry: dict[str, Any] = {}

    def record(pid: int) -> None:
        # Before tmutil may start (the child waits in the gate until this returned): the PID first,
        # then the gate's start time, which tmutil keeps after the exec.
        entry.update(pid=pid, started_at=int(time.time()))
        write_atomic(hung_path, [entry])
        lstart = ps_lstart(pid)
        if lstart not in (GONE, UNKNOWN):
            entry["lstart_utc"] = lstart
            write_atomic(hung_path, [entry])

    tmutil = env("TM_GUARD_TMUTIL", "/usr/bin/tmutil")
    # The gate: sh execs tmutil (same PID) only after reading the go line, which bounded() writes
    # after record() returned; a probe that dies before that closes the pipe and sh exits instead.
    gate = ["/bin/sh", "-c", 'read -r go || exit 97; exec "$0" "$@"', tmutil, "status", "-X"]
    done = bounded(gate, TMUTIL_TIMEOUT, stdin=b"go\n", on_start=record)
    if entry and done.status != "error":
        if done.reaped:
            write_atomic(hung_path, [])
        else:
            entry["killed_at"] = int(time.time())
            write_atomic(hung_path, [entry])
    if done.status == "timeout":
        why = "killed, exited" if done.reaped else "killed, has not exited"
        return "timeout", f"tmutil status gave no answer within {TMUTIL_TIMEOUT} s ({why})", {}
    if done.status != "ok":
        return "error", f"tmutil did not start: {done.tail()}", {}
    if done.code != 0:
        return "error", f"tmutil status exit {done.code}: {done.tail()}", {}
    try:
        return "ok", "", parse_status(done.stdout)
    except ValueError as error:
        return "error", f"tmutil status output unreadable: {error}", {}


def read_auto_backup() -> bool | None:
    done = bounded(
        [env("TM_GUARD_DEFAULTS", "/usr/bin/defaults"), "read", "/Library/Preferences/com.apple.TimeMachine", "AutoBackup"],
        DEFAULTS_TIMEOUT,
    )
    if done.status != "ok" or done.code != 0:
        return None
    value = done.stdout.decode("utf-8", "replace").strip().lower()
    return {"1": True, "true": True, "yes": True, "0": False, "false": False, "no": False}.get(value)


def ssh_argv(host: str, command: str, connect_timeout: int = 15) -> list[str]:
    return [
        env("TM_GUARD_SSH", "/usr/bin/ssh"), "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", host, command,
    ]  # fmt: skip


REMOTE_FIND_TIMEOUT = 50  # the scan's own limit on the server, inside the local BAND_TIMEOUT


def band_command(bundle: str) -> str:
    """Newest mtime under ``bands/`` and ``mapped/``; one quoted string, so fish (root on fractal) passes it to bash.

    ``timeout -s KILL`` bounds the whole pipeline on the server too: GNU
    ``timeout`` sends SIGKILL to its own process group (``bash``, ``find``,
    ``sort``, ``tail``), which nothing can ignore, so a disconnected SSH
    client leaves nothing running there.
    """

    return (
        f"timeout -s KILL {REMOTE_FIND_TIMEOUT} bash -c 'set -o pipefail; find {bundle}/bands {bundle}/mapped -type f"
        " -printf \"%T@\\n\" | sort -n | tail -n 1'"
    )


def read_bands() -> tuple[str, str, int | None]:
    """(``ok``/``failed``/``skipped``, detail, newest band write as epoch seconds)."""

    host = env("TM_GUARD_BAND_HOST", "root@fractal.tailde2ec.ts.net")
    bundle = env("TM_GUARD_BUNDLE", "/fast/timemachine/studio.sparsebundle")
    if not host or not bundle:
        return "skipped", "no backup server configured", None
    if not SAFE_HOST.fullmatch(host) or not SAFE_PATH.fullmatch(bundle):
        return "failed", "unsafe band host or bundle path", None
    done = bounded(ssh_argv(host, band_command(bundle)), BAND_TIMEOUT)
    if done.status == "timeout":
        return "failed", f"band read gave no answer within {BAND_TIMEOUT} s", None
    if done.status != "ok" or done.code != 0:
        return "failed", f"band read exit {done.code}: {done.tail()}", None
    text = done.stdout.decode("utf-8", "replace").strip()
    newest = _number(text)
    if newest is None or not 0 < newest < 10**10:
        return "failed", "band read: no band files" if not text else "band read: unreadable answer", None
    return "ok", "", int(newest)


# -- progress --------------------------------------------------------------------------------------

FINGERPRINT = ("phase", "percent", "bytes", "files", "total_bytes", "total_files", "state_changed", "stopping")


def track(previous: Any, tmutil: str, fields: dict[str, Any], band: int | None, now: int) -> tuple[dict[str, Any], int]:
    """The new progress state and ``stalled_seconds``.

    Progress is any change of the fingerprint or a band write newer than the
    newest seen so far. A backup that was not running last time starts
    counting now. While ``tmutil`` does not answer, the count carries on from
    the last known progress (the tmutil rule alerts on its own).
    """

    prev = previous if isinstance(previous, dict) and previous.get("format") == STATE_FORMAT else {}
    seen = prev.get("band_max") if isinstance(prev.get("band_max"), int) else None
    newer_band = band is not None and seen is not None and band > seen
    band_max = max(b for b in (seen, band) if b is not None) if (seen, band) != (None, None) else None
    progress_epoch = prev.get("progress_epoch") if isinstance(prev.get("progress_epoch"), int) else now
    running = prev.get("running") is True
    fingerprint = prev.get("fingerprint")
    if tmutil == "ok":
        running_now = bool(fields.get("running"))
        new_fingerprint = [fields.get(key) for key in FINGERPRINT]
        if not running_now or not running or new_fingerprint != fingerprint or newer_band:
            progress_epoch = now
        running, fingerprint = running_now, new_fingerprint
    elif running and newer_band:
        progress_epoch = now
    stalled = max(0, now - progress_epoch) if running else 0
    state = {
        "format": STATE_FORMAT,
        "running": running,
        "fingerprint": fingerprint,
        "band_max": band_max,
        "progress_epoch": progress_epoch,
        "epoch": now,
    }
    return state, stalled


# -- one cycle -------------------------------------------------------------------------------------


def cycle(state: Path, now: int) -> dict[str, Any]:
    tmutil, detail, fields = read_tmutil(state)
    auto_backup = read_auto_backup()
    band_check, band_detail, band = read_bands()
    progress, stalled = track(read_json(state / "state.json"), tmutil, fields, band, now)
    running = fields.get("running") if tmutil == "ok" else None
    if running is None:
        cross_check_ok = band_check != "failed"
    else:
        cross_check_ok = not running or band_check != "failed"
    report = {
        "host": os.uname().nodename.split(".")[0],
        "tmutil": tmutil,
        "tmutil_detail": detail,
        "running": running,
        "stopping": fields.get("stopping") if tmutil == "ok" else None,
        "phase": fields.get("phase", ""),
        "percent": fields.get("percent"),
        "bytes": fields.get("bytes"),
        "files": fields.get("files"),
        "total_bytes": fields.get("total_bytes"),
        "total_files": fields.get("total_files"),
        "auto_backup": auto_backup,
        "stalled_seconds": stalled,
        "band_check": band_check,
        "band_detail": band_detail,
        "band_newest_epoch": band,
        "cross_check_ok": cross_check_ok,
        "probe_epoch": now,
    }
    return {"report": report, "progress": progress}


def summary(report: dict[str, Any]) -> str:
    if report["tmutil"] != "ok":
        head = f"tmutil {report['tmutil']}: {report['tmutil_detail']}"
    elif report["running"]:
        head = f"running {report['phase'] or '?'}, {report['stalled_seconds'] // 60} min without progress"
    else:
        head = "idle" if report["auto_backup"] is not False else "idle, automatic backups off"
    band = "bands ok" if report["band_check"] == "ok" else f"bands {report['band_check']}: {report['band_detail']}"
    return f"{head}; {band}"


def send(report: dict[str, Any]) -> tuple[bool, str]:
    remote = env(
        "TM_GUARD_CTL",
        "/usr/bin/python3 -I /usr/local/lib/obs-daily/obs_ctl.py --config /etc/obs-daily/config.json",
    )
    host = env("TM_GUARD_HOST", "root@macmini.tailde2ec.ts.net")
    done = bounded(ssh_argv(host, f"{remote} timemachine", 20), REPORT_TIMEOUT, stdin=json.dumps(report).encode())
    if done.status == "timeout":
        return False, f"no answer within {REPORT_TIMEOUT} s"
    if done.status != "ok" or done.code != 0:
        return False, f"exit {done.code}: {done.tail()}"
    return True, ""


def cmd_check(args: argparse.Namespace) -> int:
    state = state_dir()
    with run_lock(state) as held:
        if not held:
            log("run lock unavailable")
            return 3
        now = int(time.time())
        result = cycle(state, now)
        report = result["report"]
        if args.dry_run:
            print(json.dumps(report, indent=1, sort_keys=True))
            return 0
        write_atomic(state / "state.json", result["progress"])
        line = summary(report)
        last = read_json(state / "last-summary.json")
        ok, why = send(report)
        if not ok:
            log(f"{line}; report to macmini failed ({why})")
            return 1
        # One log line per change (and every failure), not one per five minutes.
        if not isinstance(last, dict) or last.get("line") != line or args.verbose:
            log(line)
            write_atomic(state / "last-summary.json", {"line": line, "epoch": now})
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tm-guard", description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the report; no progress state, no report to macmini (the lock and the hung-tmutil record still apply)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log the summary line every run")
    args = parser.parse_args(argv)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
