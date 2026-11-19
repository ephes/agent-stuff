"""coord-watchdog: deterministic checker for the coordination pipeline.

Runs one check cycle (launchd, every 5 minutes on the Studio), compares the
coordination directory against thresholds and escalates each finding once:
(a) a message into the coordinator session when a non-interactive mechanism is
configured (none exists today, so this stage is skipped), (b) after the
finding persisted for ESCALATE_MIN one bounded headless Claude diagnosis run,
(c) a notification to the owner when that run has finished (or could not
start). No LLM in the normal path; never reads session transcripts.

Python 3 stdlib only. See README.md for the checks, settings and state files.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()
TOOL_DIR = Path(__file__).resolve().parent
BRIEF_TEMPLATE = TOOL_DIR / "diag-brief.md"

# Every setting: name -> (default, kind). Read from CW_<NAME> in the
# environment, after an optional --config file of NAME=VALUE lines.
DEFAULTS: dict[str, tuple[str, str]] = {
    "COORD_DIR": (str(HOME / "workspaces/ws-work-planning/coordination"), "path"),
    "STATE_DIR": ("", "path"),  # default: <COORD_DIR>/watchdog
    "STUCK_MIN": ("60", "float"),
    "CPU_PROGRESS_SEC": ("20", "float"),
    "ACK_MIN": ("30", "float"),
    "HEARTBEAT_MIN": ("45", "float"),
    "AUTOMERGE_OFF_MAX_MIN": ("1440", "float"),
    "QUEUE_STALL_MIN": ("120", "float"),
    "USAGE_MAX_AGE": ("1h", "str"),
    "USAGE_PROVIDERS": ("claude", "str"),  # comma list; empty: every provider
    "LOAD_THRESHOLD": ("", "float"),  # default: 2.5 x CPU count
    "LOAD_SUSTAIN_MIN": ("30", "float"),
    "SWAP_THRESHOLD_GB": ("16", "float"),
    "SWAP_SUSTAIN_MIN": ("15", "float"),
    "ESCALATE_MIN": ("15", "float"),
    "DIAG_ENABLED": ("1", "bool"),
    "DIAG_TIMEOUT_MIN": ("15", "float"),
    "DIAG_MIN_INTERVAL_MIN": ("60", "float"),
    "DIAG_MODEL": ("claude-opus-5-5", "str"),
    "MESSAGE_CMD": ("", "str"),
    "FEEDER_ENV": ("BACKLOG_MAX=20 BACKLOG_HOURS=48", "str"),
    "NOTIFY_HERDR": ("1", "bool"),
    "NOTIFY_WORK_ITEM": ("coord-watchdog", "str"),
    "CLAUDE_BIN": ("claude", "str"),
    "WORK_BIN": ("work", "str"),
    "HERDR_BIN": ("herdr", "str"),
    "PYTHON_BIN": (sys.executable, "str"),
    # Test hooks.
    "PS_OUT": ("", "path"),
    "LOADAVG": ("", "str"),
    "SWAPUSAGE": ("", "str"),  # instead of `sysctl -n vm.swapusage`
    "NOW": ("", "float"),
}


class ConfigError(Exception):
    pass


def read_config_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{n}: expected NAME=VALUE")
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("CW_")
        if key not in DEFAULTS:
            raise ConfigError(f"{path}:{n}: unknown setting {key}")
        values[key] = value.strip()
    return values


def parse_duration_minutes(value: str) -> float:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*", value)
    if not m:
        raise ConfigError(f"bad duration {value!r}")
    n = float(m.group(1))
    return n * {"s": 1 / 60, "m": 1, "h": 60, "d": 1440, "": 1}[m.group(2)]


@dataclass
class Config:
    raw: dict[str, str]

    @classmethod
    def load(cls, config_file: str | None, env: dict[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        raw = {k: d for k, (d, _) in DEFAULTS.items()}
        if config_file:
            raw.update(read_config_file(Path(config_file).expanduser()))
        for key in DEFAULTS:
            if f"CW_{key}" in env:
                raw[key] = env[f"CW_{key}"]
        cfg = cls(raw)
        for key, (_, kind) in DEFAULTS.items():
            value = raw[key]
            if kind == "float" and value != "":
                try:
                    float(value)
                except ValueError:
                    raise ConfigError(f"{key}: not a number: {value!r}") from None
        if raw["USAGE_MAX_AGE"]:
            parse_duration_minutes(raw["USAGE_MAX_AGE"])
        return cfg

    def s(self, key: str) -> str:
        return self.raw[key]

    def f(self, key: str) -> float:
        return float(self.raw[key])

    def b(self, key: str) -> bool:
        return self.raw[key].strip().lower() in ("1", "true", "yes", "on")

    def path(self, key: str) -> Path:
        return Path(self.raw[key]).expanduser()

    @property
    def coord_dir(self) -> Path:
        return self.path("COORD_DIR")

    @property
    def state_dir(self) -> Path:
        return self.path("STATE_DIR") if self.raw["STATE_DIR"] else self.coord_dir / "watchdog"

    @property
    def load_threshold(self) -> float:
        if self.raw["LOAD_THRESHOLD"]:
            return self.f("LOAD_THRESHOLD")
        return 2.5 * (os.cpu_count() or 1)

    def now(self) -> float:
        return self.f("NOW") if self.raw["NOW"] else time.time()


# ---------------------------------------------------------------- processes


@dataclass
class Proc:
    pid: int
    ppid: int
    cpu: float
    command: str


def parse_cputime(value: str) -> float:
    """ps TIME: [dd-][hh:]mm:ss[.cc]."""
    days = 0
    if "-" in value:
        d, value = value.split("-", 1)
        days = int(d)
    total = 0.0
    for part in value.split(":"):
        total = total * 60 + float(part)
    return days * 86400 + total


def read_procs(cfg: Config) -> dict[int, Proc]:
    if cfg.raw["PS_OUT"]:
        text = cfg.path("PS_OUT").read_text()
    else:
        text = subprocess.run(
            ["ps", "-axwwS", "-o", "pid=,ppid=,time=,command="],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    procs: dict[int, Proc] = {}
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            p = Proc(int(parts[0]), int(parts[1]), parse_cputime(parts[2]), parts[3])
        except ValueError:
            continue
        procs[p.pid] = p
    return procs


def tree_cpu(procs: dict[int, Proc], root: int) -> float:
    children: dict[int, list[int]] = {}
    for p in procs.values():
        children.setdefault(p.ppid, []).append(p.pid)
    total, todo, seen = 0.0, [root], set()
    while todo:
        pid = todo.pop()
        if pid in seen or pid not in procs:
            continue
        seen.add(pid)
        total += procs[pid].cpu
        todo.extend(children.get(pid, []))
    return total


RUN_SH = re.compile(r"^(?:\S*/)?bash\s+(\S*run\.sh)\s+(\S+)\s*$")


def katharina_workers(cfg: Config, procs: dict[int, Proc]) -> dict[str, Proc]:
    """Running `run.sh <name>` processes of coordination/katharina."""
    kdir = cfg.coord_dir / "katharina"
    cdir = cfg.coord_dir / "codex"
    out: dict[str, Proc] = {}
    for p in procs.values():
        m = RUN_SH.match(p.command)
        if not m:
            continue
        script, name = m.groups()
        if script.startswith("/"):
            if Path(script).parent.resolve() != kdir.resolve():
                continue
        elif not (kdir / f"{name}.md").exists() or (cdir / f"{name}.md").exists():
            continue
        out[name] = p
    return out


def size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return -1


def mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def minutes(seconds: float) -> str:
    return f"{seconds / 60:.0f} min"


# ---------------------------------------------------------------- checks


@dataclass
class Finding:
    key: str
    kind: str
    detail: str


@dataclass
class CheckResult:
    findings: list[Finding] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def add(self, key: str, kind: str, detail: str) -> None:
        self.findings.append(Finding(key, kind, detail))


def check_codex(cfg: Config, procs: dict[int, Proc], now: float, res: CheckResult) -> None:
    cdir = cfg.coord_dir / "codex"
    if not cdir.is_dir():
        res.add("codex-dir", "codex-dir-missing", f"{cdir} does not exist")
        return
    lock = cdir / "feeder.lock"
    pid = None
    try:
        pid = int(os.readlink(lock))
    except (OSError, ValueError):
        pass
    alive = pid is not None and pid in procs and "feeder" in procs[pid].command
    deliberate = [f for f in ("stop.flag", "autoround.off") if (cdir / f).exists()]
    if alive:
        res.info.append(f"feeder alive (pid {pid})")
    elif deliberate:
        res.info.append(f"feeder not running; deliberate pause: {', '.join(deliberate)}")
    else:
        res.add("feeder-dead", "feeder-dead",
                f"codex/feeder.sh is not running (lock pid {pid}) and neither stop.flag nor autoround.off exists")
    queue = cdir / "queue.txt"
    try:
        entries = [ln for ln in queue.read_text().splitlines() if ln.strip()]
    except OSError:
        entries = []
    running = sum(1 for p in procs.values() if "codex exec" in p.command)
    res.info.append(f"codex queue {len(entries)}, running codex jobs {running}")
    if entries and alive:
        started = mtime(cdir / "started.txt") or 0
        last = ""
        try:
            with open(cdir / "feeder.log", "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 4096))
                lines = fh.read().decode(errors="replace").strip().splitlines()
                last = lines[-1] if lines else ""
        except OSError:
            pass
        idle = now - started
        if idle > cfg.f("QUEUE_STALL_MIN") * 60 and "quota guard refused" not in last:
            res.add("codex-queue-stalled", "codex-queue-stalled",
                    f"{len(entries)} briefs queued, nothing started for {minutes(idle)}; feeder.log: {last[:120]}")
    off = cfg.coord_dir / "katharina" / "automerge.off"
    off_m = mtime(off)
    if off_m is not None:
        age = now - off_m
        res.info.append(f"automerge.off present for {minutes(age)}")
        if age > cfg.f("AUTOMERGE_OFF_MAX_MIN") * 60:
            reason = ""
            try:
                reason = off.read_text().strip().splitlines()[0][:120]
            except (OSError, IndexError):
                pass
            res.add("automerge-off", "automerge-off-old",
                    f"katharina/automerge.off exists for {minutes(age)}: {reason}")


def check_katharina(cfg: Config, procs: dict[int, Proc], now: float, state: dict,
                    res: CheckResult) -> None:
    kdir = cfg.coord_dir / "katharina"
    if not kdir.is_dir():
        res.add("katharina-dir", "katharina-dir-missing", f"{kdir} does not exist")
        return
    workers = katharina_workers(cfg, procs)
    old = state.get("workers", {})
    new: dict[str, dict] = {}
    for name, p in sorted(workers.items()):
        cpu = tree_cpu(procs, p.pid)
        log_size = size(kdir / "logs" / f"{name}.log")
        out_size = size(kdir / f"{name}.out")
        prev = old.get(name)
        if not prev or prev.get("pid") != p.pid:
            entry = {"pid": p.pid, "cpu": cpu, "cpu_acc": 0.0, "log": log_size, "out": out_size,
                     "progress_at": now}
        else:
            # Add up only increases against the last cycle: the tree total drops
            # when a child that ps could not fold into its parent exits.
            entry = dict(prev)
            entry["cpu_acc"] = prev.get("cpu_acc", 0.0) + max(0.0, cpu - prev.get("cpu", cpu))
            entry["cpu"] = cpu
            if (log_size != prev.get("log") or out_size != prev.get("out")
                    or entry["cpu_acc"] >= cfg.f("CPU_PROGRESS_SEC")):
                entry.update(cpu_acc=0.0, log=log_size, out=out_size, progress_at=now)
        new[name] = entry
        quiet = now - entry["progress_at"]
        if quiet > cfg.f("STUCK_MIN") * 60:
            res.add(f"stuck:{name}", "worker-stuck",
                    f"katharina worker {name} (pid {p.pid}): no log/output growth and under "
                    f"{cfg.f('CPU_PROGRESS_SEC'):.0f}s CPU for {minutes(quiet)}")
    state["workers"] = new
    res.info.append(f"katharina workers running {len(workers)}")

    since = state.get("since", now)
    acks = cfg.coord_dir / "acks"
    unacked = 0
    for out in sorted(kdir.glob("*.out")):
        name = out.name[:-4]
        if name in workers:
            continue
        finished = max(filter(None, [mtime(out), mtime(kdir / "logs" / f"{name}.log")]), default=0)
        if finished < since:
            continue
        ack = mtime(acks / name)
        if ack is not None and ack >= finished:
            continue
        age = now - finished
        if age > cfg.f("ACK_MIN") * 60:
            unacked += 1
            res.add(f"unacked:{name}", "report-unacked",
                    f"katharina/{name}.out finished {minutes(age)} ago, no coordination/acks/{name}")
    if unacked:
        res.info.append(f"unacknowledged reports {unacked}")


def check_usage(cfg: Config, res: CheckResult) -> None:
    providers = [p.strip() for p in cfg.s("USAGE_PROVIDERS").split(",") if p.strip()] or [""]
    stale, failed = [], []
    for provider in providers:
        cmd = [cfg.s("WORK_BIN"), "usage", "status"]
        if cfg.s("USAGE_MAX_AGE"):
            cmd += ["--max-age", cfg.s("USAGE_MAX_AGE")]
        if provider:
            cmd += ["--provider", provider]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failed.append(f"{' '.join(cmd[1:])}: {exc}")
            continue
        if r.returncode == 0:
            continue
        lines = [" ".join(ln.split()) for ln in (r.stdout + "\n" + r.stderr).splitlines()
                 if ln.strip() and not ln.lstrip().lower().startswith("fresh")]
        if r.returncode == 2:
            stale.append("; ".join(lines) or f"{provider or 'all'}: stale")
        else:
            failed.append(f"{' '.join(cmd[1:])} exit {r.returncode}: {'; '.join(lines)}")
    if stale:
        res.add("usage-stale", "usage-stale", "work usage status: " + "; ".join(stale)[:300])
    if failed:
        res.add("usage-check", "usage-check-failed", "; ".join(failed)[:300])
    if not stale and not failed:
        res.info.append(f"usage fresh ({', '.join(p or 'all' for p in providers)})")


def check_heartbeat(cfg: Config, now: float, res: CheckResult) -> None:
    hb = cfg.coord_dir / "coordinator.heartbeat"
    m = mtime(hb)
    if m is None:
        res.add("heartbeat", "heartbeat-stale", "coordination/coordinator.heartbeat is missing")
    elif now - m > cfg.f("HEARTBEAT_MIN") * 60:
        res.add("heartbeat", "heartbeat-stale",
                f"coordinator.heartbeat last touched {minutes(now - m)} ago")
    else:
        res.info.append(f"heartbeat {minutes(now - m)} old")


def check_load(cfg: Config, now: float, state: dict, res: CheckResult) -> None:
    if cfg.s("LOADAVG"):
        load5 = float(cfg.s("LOADAVG"))
    else:
        load5 = os.getloadavg()[1]
    threshold = cfg.load_threshold
    res.info.append(f"load5 {load5:.1f} (threshold {threshold:.1f})")
    if load5 <= threshold:
        state.pop("load_high_since", None)
        return
    since = state.setdefault("load_high_since", now)
    if now - since >= cfg.f("LOAD_SUSTAIN_MIN") * 60:
        res.add("load", "load-high",
                f"5-min load {load5:.1f} above {threshold:.1f} for {minutes(now - since)}")


def swap_used_bytes(text: str) -> float | None:
    """``used`` from ``sysctl -n vm.swapusage`` ("total = 1024.00M  used = 252.88M  free = ...")."""

    m = re.search(r"used\s*=\s*(\d+(?:\.\d+)?)([KMGT]?)", text)
    if not m:
        return None
    return float(m.group(1)) * 1024 ** "_KMGT".index(m.group(2) or "_")


def check_swap(cfg: Config, now: float, state: dict, res: CheckResult) -> None:
    text = cfg.s("SWAPUSAGE")
    if not text:
        try:
            text = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True,
                                  text=True, timeout=10, check=False).stdout
        except (OSError, subprocess.TimeoutExpired):
            text = ""
    used = swap_used_bytes(text)
    threshold = cfg.f("SWAP_THRESHOLD_GB")
    if used is None:
        res.info.append("swap unknown")
        since = state.get("swap_high_since")
        if since is not None and "swap" in state.get("findings", {}):
            # A failed read is no recovery: an open finding stays open (no resolve/reopen pair).
            # Only a readable high sample opens one.
            res.add("swap", "swap-high",
                    f"swap above {threshold:.0f} GB since {minutes(now - since)} ago (current reading failed)")
        return
    gb = used / 1024 ** 3
    res.info.append(f"swap {gb:.1f} GB (threshold {threshold:.0f} GB)")
    if gb <= threshold:
        state.pop("swap_high_since", None)
        return
    since = state.setdefault("swap_high_since", now)
    if now - since >= cfg.f("SWAP_SUSTAIN_MIN") * 60:
        res.add("swap", "swap-high",
                f"swap in use {gb:.1f} GB above {threshold:.0f} GB for {minutes(now - since)}")


def run_checks(cfg: Config, state: dict, now: float) -> CheckResult:
    res = CheckResult()
    procs = read_procs(cfg)
    check_codex(cfg, procs, now, res)
    check_katharina(cfg, procs, now, state, res)
    check_usage(cfg, res)
    check_heartbeat(cfg, now, res)
    check_load(cfg, now, state, res)
    check_swap(cfg, now, state, res)
    return res


# ---------------------------------------------------------------- escalation


def log_line(cfg: Config, name: str, text: str, now: float) -> None:
    path = cfg.state_dir / name
    try:
        if path.stat().st_size > 1_000_000:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now))
    with open(path, "a") as fh:
        fh.write(f"{stamp} {text}\n")


def run_quiet(cmd: list[str], timeout: float) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, " ".join((r.stdout + " " + r.stderr).split())[:200]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)[:200]


def send_message(cfg: Config, findings: list[Finding], now: float) -> bool:
    """Stage (a). Only with MESSAGE_CMD; the message is its last argument."""
    if not cfg.s("MESSAGE_CMD"):
        return False
    text = "Watchdog: " + "; ".join(f"{f.kind}: {f.detail}" for f in findings)
    rc, out = run_quiet(shlex.split(cfg.s("MESSAGE_CMD")) + [text[:900]], 60)
    log_line(cfg, "watchdog.log", f"message rc={rc} {out}", now)
    return rc == 0


def notify(cfg: Config, title: str, body: str, now: float) -> None:
    """Stage (c): file always, herdr and the work-app note best effort."""
    log_line(cfg, "notifications.log", f"{title} | {body}", now)
    if cfg.b("NOTIFY_HERDR"):
        rc, out = run_quiet([cfg.s("HERDR_BIN"), "notification", "show", title,
                             "--body", body[:300], "--sound", "request"], 15)
        if rc != 0:
            log_line(cfg, "watchdog.log", f"herdr notification failed rc={rc} {out}", now)
    if cfg.s("NOTIFY_WORK_ITEM"):
        rc, out = run_quiet([cfg.s("WORK_BIN"), "note", cfg.s("NOTIFY_WORK_ITEM"),
                             f"{title}: {body}"[:1500]], 60)
        if rc != 0:
            log_line(cfg, "watchdog.log", f"work note failed rc={rc} {out}", now)


def render_brief(cfg: Config, findings: list[Finding], run_dir: Path) -> str:
    template = BRIEF_TEMPLATE.read_text()
    listing = "\n".join(f"- `{f.key}` ({f.kind}): {f.detail}" for f in findings)
    values = {
        "COORD_DIR": str(cfg.coord_dir),
        "FINDINGS": listing,
        "RUN_DIR": str(run_dir),
        "ESCALATE_MIN": f"{cfg.f('ESCALATE_MIN'):g}",
        "DIAG_TIMEOUT_MIN": f"{cfg.f('DIAG_TIMEOUT_MIN'):g}",
        "RESTART_FEEDER": " ".join(shlex.quote(a) for a in (
            cfg.s("PYTHON_BIN"), str(TOOL_DIR / "bin" / "coord-watchdog"), "restart-feeder")),
        "FEEDER_ENV": cfg.s("FEEDER_ENV"),
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def diag_running(cfg: Config, state: dict, now: float) -> bool:
    diag = state.get("diag")
    if not diag or diag.get("done"):
        return False
    status = Path(diag["dir"]) / "status.json"
    if status.exists():
        return False
    # Lost supervisor: give up waiting well after its own timeout.
    return now - diag["started"] < (cfg.f("DIAG_TIMEOUT_MIN") + 10) * 60


def start_diag(cfg: Config, findings: list[Finding], now: float) -> dict | None:
    run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    run_dir = cfg.state_dir / f"diag-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "brief.md").write_text(render_brief(cfg, findings, run_dir))
    cmd = [cfg.s("PYTHON_BIN"), str(TOOL_DIR / "bin" / "coord-watchdog"),
           "diag-run", "--run-dir", str(run_dir)]
    env = dict(os.environ)
    env.update({f"CW_{k}": v for k, v in cfg.raw.items()})
    try:
        with open(run_dir / "supervisor.log", "w") as log:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, env=env)
    except OSError as exc:
        log_line(cfg, "watchdog.log", f"diag start failed: {exc}", now)
        return None
    return {"id": run_id, "dir": str(run_dir), "started": now,
            "keys": [f.key for f in findings], "done": False}


def diag_summary(diag: dict) -> str:
    run_dir = Path(diag["dir"])
    try:
        status = json.loads((run_dir / "status.json").read_text())
    except (OSError, ValueError):
        status = {"rc": None, "timed_out": None, "lost": True}
    try:
        text = " ".join((run_dir / "summary.md").read_text().split())
    except OSError:
        text = ""
    if status.get("lost"):
        head = "Diagnoselauf ohne Ergebnis (Supervisor verloren)"
    elif status.get("timed_out"):
        head = "Diagnoselauf nach Zeitlimit abgebrochen"
    elif status.get("rc") != 0:
        head = f"Diagnoselauf fehlgeschlagen (exit {status.get('rc')})"
    else:
        head = "Diagnose"
    return f"{head}: {text[:600]}" if text else head


def escalate(cfg: Config, state: dict, res: CheckResult, now: float) -> None:
    known: dict = state.setdefault("findings", {})
    current = {f.key: f for f in res.findings}
    for key in list(known):
        if key not in current:
            log_line(cfg, "watchdog.log", f"resolved {key}", now)
            del known[key]
    fresh = []
    for f in res.findings:
        entry = known.get(f.key)
        if entry is None:
            entry = known[f.key] = {"kind": f.kind, "first_seen": now, "message": False,
                                    "diag": None, "notified": False}
            log_line(cfg, "watchdog.log", f"new {f.key}: {f.detail}", now)
            fresh.append(f)
        entry["detail"] = f.detail
        entry["last_seen"] = now
    if fresh and send_message(cfg, fresh, now):
        for f in fresh:
            known[f.key]["message"] = True

    # (c) notify once per finding: after its diagnosis run (finished before
    # a new run may replace state["diag"]), or right away when no run was
    # possible.
    diag = state.get("diag")
    if diag and not diag.get("done") and not diag_running(cfg, state, now):
        diag["done"] = True
        summary = diag_summary(diag)
        log_line(cfg, "watchdog.log", f"diag {diag['id']} finished: {summary[:200]}", now)
        open_keys = [k for k in diag["keys"] if k in known]
        if open_keys:
            notify(cfg, f"Koordinations-Watchdog: {len(open_keys)} Befund(e) offen",
                   "; ".join(f"{k}: {known[k]['detail']}" for k in open_keys)
                   + f" | {summary} | {diag['dir']}", now)
        else:
            notify(cfg, "Koordinations-Watchdog: Befunde behoben",
                   f"{', '.join(diag['keys'])} | {summary} | {diag['dir']}", now)
        for k in open_keys:
            known[k]["notified"] = True
    # (b) one diagnosis run per finding, one at a time, rate-limited.
    due = [current[k] for k, e in known.items()
           if e["diag"] is None and not e["notified"]
           and now - e["first_seen"] >= cfg.f("ESCALATE_MIN") * 60]
    if due and not diag_running(cfg, state, now):
        last = state.get("last_diag_start", 0)
        if not cfg.b("DIAG_ENABLED"):
            for f in due:
                known[f.key]["diag"] = "disabled"
        elif now - last < cfg.f("DIAG_MIN_INTERVAL_MIN") * 60:
            for f in due:
                known[f.key]["diag"] = "rate-limited"
        else:
            started = start_diag(cfg, due, now)
            if started:
                state["diag"] = started
                state["last_diag_start"] = now
                log_line(cfg, "watchdog.log", f"diag {started['id']} started for {started['keys']}", now)
                for f in due:
                    known[f.key]["diag"] = started["id"]
            else:
                for f in due:
                    known[f.key]["diag"] = "failed"

    reasons = {"disabled": "Diagnose deaktiviert",
               "failed": "Diagnoselauf konnte nicht starten",
               "rate-limited": "kein neuer Diagnoselauf (letzter vor weniger als "
                               f"{cfg.f('DIAG_MIN_INTERVAL_MIN'):.0f} min)"}
    direct = [k for k, e in known.items() if e["diag"] in reasons and not e["notified"]]
    if direct:
        why = "; ".join(sorted({reasons[known[k]["diag"]] for k in direct}))
        notify(cfg, f"Koordinations-Watchdog: {len(direct)} Befund(e) offen",
               "; ".join(f"{k}: {known[k]['detail']}" for k in direct) + f" | {why}", now)
        for k in direct:
            known[k]["notified"] = True


# ---------------------------------------------------------------- diag supervisor


def claude_env(cfg: Config) -> dict[str, str]:
    """Same account choice as katharina/run.sh."""
    env = dict(os.environ)
    try:
        until = int((cfg.coord_dir / "katharina" / "account.main").read_text().strip() or 0)
    except (OSError, ValueError):
        until = 0
    if time.time() < until:
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = str(HOME / ".claude-katharina")
    return env


def diag_run(cfg: Config, run_dir: Path) -> int:
    brief = (run_dir / "brief.md").read_text()
    brief += ("\n\nRunner note: you run headless (claude -p) and are killed after the time limit. "
              "Your process ends with your final message. Work in the foreground and start no "
              "background jobs; the restart-feeder command detaches the feeder by itself.\n")
    cmd = [cfg.s("CLAUDE_BIN"), "-p", "--permission-mode", "auto", "--model", cfg.s("DIAG_MODEL")]
    timeout = cfg.f("DIAG_TIMEOUT_MIN") * 60
    workdir = HOME / "workspaces"
    status = {"rc": None, "timed_out": False, "started": time.time()}
    with open(run_dir / "summary.md", "w") as out, open(run_dir / "claude.log", "w") as err:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, text=True,
                                    cwd=workdir if workdir.is_dir() else None,
                                    env=claude_env(cfg), start_new_session=True)
        except OSError as exc:
            status.update(rc=-1, error=str(exc))
        else:
            try:
                proc.communicate(brief, timeout=timeout)
                status["rc"] = proc.returncode
            except subprocess.TimeoutExpired:
                status["timed_out"] = True
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    proc.wait()
                status["rc"] = proc.returncode
    status["finished"] = time.time()
    tmp = run_dir / "status.json.tmp"
    tmp.write_text(json.dumps(status))
    tmp.replace(run_dir / "status.json")
    return 0


# ---------------------------------------------------------------- feeder restart


def restart_feeder(cfg: Config) -> int:
    """The diagnosis run's only fix: start a dead feeder, detached, with FEEDER_ENV."""
    cdir = cfg.coord_dir / "codex"
    procs = read_procs(cfg)
    try:
        pid = int(os.readlink(cdir / "feeder.lock"))
    except (OSError, ValueError):
        pid = None
    if pid is not None and pid in procs and "feeder" in procs[pid].command:
        print(f"feeder already running (pid {pid}); nothing to do")
        return 1
    flags = [f for f in ("stop.flag", "autoround.off") if (cdir / f).exists()]
    if flags:
        print(f"deliberate pause ({', '.join(flags)}); not restarting")
        return 1
    env = dict(os.environ)
    for item in shlex.split(cfg.s("FEEDER_ENV")):
        key, _, value = item.partition("=")
        env[key] = value
    log_path = cdir / "feeder.log"
    offset = size(log_path)
    with open(log_path, "a") as log:
        proc = subprocess.Popen(["./feeder.sh"], cwd=cdir, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, env=env, start_new_session=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with open(log_path, "rb") as fh:
                fh.seek(max(0, offset))
                new = fh.read().decode(errors="replace")
        except OSError:
            new = ""
        if f"feeder started (pid {proc.pid}" in new:
            print(f"feeder started (pid {proc.pid}, {cfg.s('FEEDER_ENV')})")
            return 0
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    print(f"feeder did not report a start (exit {proc.poll()}); feeder.log: {new.strip()[-300:]}")
    return 2


# ---------------------------------------------------------------- main


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(path)


def cmd_check(cfg: Config, args: argparse.Namespace) -> int:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.state_dir / "lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("coord-watchdog: another check is running", file=sys.stderr)
            return 3
        return check_locked(cfg, args)


def check_locked(cfg: Config, args: argparse.Namespace) -> int:
    now = cfg.now()
    state_path = cfg.state_dir / "state.json"
    state = load_state(state_path)
    state.setdefault("since", now)
    res = run_checks(cfg, state, now)
    if args.dry_run:
        state_after = state
    else:
        escalate(cfg, state, res, now)
        state["last_check"] = now
        save_state(state_path, state)
        state_after = state
        latest = {"checked_at": now, "info": res.info,
                  "findings": [{"key": f.key, "kind": f.kind, "detail": f.detail,
                                **{k: v for k, v in state_after["findings"].get(f.key, {}).items()
                                   if k in ("first_seen", "diag", "notified")}}
                               for f in res.findings]}
        (cfg.state_dir / "latest.json").write_text(json.dumps(latest, indent=1))
        log_line(cfg, "watchdog.log",
                 f"check findings={len(res.findings)} {[f.key for f in res.findings]}", now)
    if args.json:
        print(json.dumps({"info": res.info,
                          "findings": [f.__dict__ for f in res.findings]}, indent=1))
    else:
        for f in res.findings:
            print(f"{f.key}\t{f.kind}\t{f.detail}")
        if args.verbose:
            for line in res.info:
                print(f"# {line}")
    return 1 if res.findings else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coord-watchdog", description=__doc__.splitlines()[0])
    parser.add_argument("--config", help="NAME=VALUE settings file (CW_<NAME> env vars override)")
    sub = parser.add_subparsers(dest="cmd")
    check = sub.add_parser("check", help="run one check cycle (default)")
    check.add_argument("--dry-run", action="store_true", help="check only: no state, no escalation")
    check.add_argument("--json", action="store_true")
    check.add_argument("-v", "--verbose", action="store_true", help="also print info lines")
    sub.add_parser("restart-feeder", help="start a dead Codex feeder detached with FEEDER_ENV")
    dr = sub.add_parser("diag-run", help="internal: supervise one diagnosis run")
    dr.add_argument("--run-dir", required=True)
    parser.set_defaults(dry_run=False, json=False, verbose=False)
    args = parser.parse_args(argv)
    try:
        cfg = Config.load(args.config)
    except (ConfigError, OSError) as exc:
        print(f"coord-watchdog: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "diag-run":
        return diag_run(cfg, Path(args.run_dir))
    if args.cmd == "restart-feeder":
        return restart_feeder(cfg)
    return cmd_check(cfg, args)
