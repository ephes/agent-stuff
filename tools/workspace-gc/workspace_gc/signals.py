"""In-use signals: herdr panes, process working directories, work-app items.

Each source reports a status:
  ok      - read successfully
  absent  - the source does not exist on this machine (no herdr binary, no
            work env file); tolerated
  skipped - turned off on the command line
  error   - it exists but could not be read

`--apply` refuses to remove anything unless every source is ok or absent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

# Stages after which an item's worktree is no longer needed (see the
# work-ledger skill's closeout rule). Every other stage keeps it.
CLOSED_STAGES = frozenset({"merged", "installed", "accepted", "dropped"})

_TOKENISH = re.compile(r"[A-Za-z0-9_\-]{24,}")


def _sanitize(text: str) -> str:
    line = (text or "").strip().splitlines()
    first = line[-1] if line else ""
    return _TOKENISH.sub("[redacted]", first)[:160]


@dataclass
class SourceStatus:
    status: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail}


@dataclass
class WorkRef:
    slug: str
    stage: str
    worktree: str  # normalized absolute path

    @property
    def active(self) -> bool:
        return self.stage not in CLOSED_STAGES


@dataclass
class Signals:
    herdr_cwds: list[str] = field(default_factory=list)
    process_cwds: list[str] = field(default_factory=list)
    work_refs: list[WorkRef] = field(default_factory=list)
    status: dict[str, SourceStatus] = field(default_factory=dict)

    def apply_blockers(self) -> list[str]:
        return [f"{name}: {st.status}{' (' + st.detail + ')' if st.detail else ''}"
                for name, st in sorted(self.status.items())
                if st.status not in ("ok", "absent")]


def normalize_path(p: str) -> str:
    p = os.path.expanduser(p.strip())
    if not os.path.isabs(p):
        return ""
    p = os.path.normpath(p)
    return os.path.realpath(p) if os.path.exists(p) else p


def read_herdr(herdr: str | None = None) -> tuple[list[str], SourceStatus]:
    exe = herdr or shutil.which("herdr")
    if not exe:
        return [], SourceStatus("absent", "herdr not installed")
    try:
        proc = subprocess.run([exe, "pane", "list"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], SourceStatus("error", type(exc).__name__)
    if proc.returncode != 0:
        return [], SourceStatus("error", f"exit {proc.returncode}: {_sanitize(proc.stderr)}")
    try:
        data = json.loads(proc.stdout)
        panes = data["result"]["panes"]
    except (ValueError, KeyError, TypeError):
        return [], SourceStatus("error", "unexpected output")
    cwds = set()
    for pane in panes:
        for key in ("cwd", "foreground_cwd"):
            v = pane.get(key)
            if isinstance(v, str) and v:
                n = normalize_path(v)
                if n:
                    cwds.add(n)
    return sorted(cwds), SourceStatus("ok", f"{len(panes)} panes")


def read_process_cwds() -> tuple[list[str], SourceStatus]:
    exe = shutil.which("lsof") or ("/usr/sbin/lsof" if os.path.exists("/usr/sbin/lsof") else None)
    if not exe:
        return [], SourceStatus("absent", "lsof not installed")
    try:
        proc = subprocess.run([exe, "-a", "-d", "cwd", "-u", str(os.getuid()), "-Fpn"],
                              capture_output=True, text=True, timeout=60, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], SourceStatus("error", type(exc).__name__)
    if not proc.stdout:
        return [], SourceStatus("error", f"exit {proc.returncode}, no output")
    me = os.getpid()
    cwds = set()
    pid = None
    for line in proc.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:]) if line[1:].isdigit() else None
        elif line.startswith("n") and pid != me:
            n = normalize_path(line[1:])
            if n:
                cwds.add(n)
    if proc.returncode != 0:
        # Partial output: some processes could not be inspected. Keep what was
        # read for the report, but block --apply.
        return sorted(cwds), SourceStatus("error", f"lsof exit {proc.returncode} (partial)")
    return sorted(cwds), SourceStatus("ok", f"{len(cwds)} distinct cwds")


def _work_cmd(env_file: str, ledger_dir: str, args: list[str]) -> subprocess.CompletedProcess:
    # The env file is sourced by bash inside the child only; its values never
    # pass through this process's arguments or output.
    script = 'set -a && . "$0" && set +a && exec uv run --quiet work "$@"'
    return subprocess.run(["bash", "-c", script, env_file, *args], cwd=ledger_dir,
                          capture_output=True, text=True, timeout=120)


def run_work(env_file: str, ledger_dir: str, args: list[str]) -> tuple[int, str, str]:
    try:
        proc = _work_cmd(env_file, ledger_dir, args)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 255, "", type(exc).__name__
    return proc.returncode, proc.stdout, _sanitize(proc.stderr)


def work_available(env_file: str, ledger_dir: str) -> SourceStatus | None:
    if not os.path.isfile(env_file):
        return SourceStatus("absent", "no work env file")
    if not os.path.isdir(ledger_dir):
        return SourceStatus("error", "work-ledger checkout missing")
    return None


def read_work_items(env_file: str, ledger_dir: str) -> tuple[list[WorkRef], SourceStatus]:
    unavailable = work_available(env_file, ledger_dir)
    if unavailable:
        return [], unavailable
    code, stdout, err = run_work(env_file, ledger_dir, ["items", "--json"])
    if code != 0:
        return [], SourceStatus("error", f"work items exit {code}: {err}")
    try:
        slugs = [i["slug"] for i in json.loads(stdout)["items"]]
    except (ValueError, KeyError, TypeError):
        return [], SourceStatus("error", "unexpected work items output")

    def show(slug: str):
        c, o, e = run_work(env_file, ledger_dir, ["show", "--json", slug])
        if c != 0:
            raise RuntimeError(f"work show {slug} exit {c}: {e}")
        return json.loads(o)["item"]

    refs: list[WorkRef] = []
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for item in pool.map(show, slugs):
                wt = item.get("worktree") or ""
                n = normalize_path(wt) if wt else ""
                if n:
                    refs.append(WorkRef(item["slug"], item.get("stage", ""), n))
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        return [], SourceStatus("error", _sanitize(str(exc)))
    return refs, SourceStatus("ok", f"{len(slugs)} items, {len(refs)} with worktree")


def gather(*, herdr: bool = True, processes: bool = True, work: bool = True,
           work_env: str = "", work_ledger: str = "") -> Signals:
    s = Signals()
    if herdr:
        s.herdr_cwds, s.status["herdr"] = read_herdr()
    else:
        s.status["herdr"] = SourceStatus("skipped")
    if processes:
        s.process_cwds, s.status["processes"] = read_process_cwds()
    else:
        s.status["processes"] = SourceStatus("skipped")
    if work:
        s.work_refs, s.status["work"] = read_work_items(work_env, work_ledger)
    else:
        s.status["work"] = SourceStatus("skipped")
    return s
