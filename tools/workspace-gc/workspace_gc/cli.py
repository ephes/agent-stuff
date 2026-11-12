"""workspace-gc - inventory agent checkouts and remove the safe ones.

  workspace-gc [scan] [--json] [--apply]   inventory the roots (dry run unless --apply)
  workspace-gc remove [--apply] PATH       guarded removal of one checkout
  workspace-gc report --out-dir DIR [--apply]
                                           the same run as scan, written to
                                           DIR/latest.{txt,json} (the scheduled job
                                           passes --apply; without it: dry run)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile

from . import budget
from . import empties
from . import husks
from . import inventory as inv_mod
from . import remove as rm_mod
from . import report as rep
from . import runlock
from . import signals as sig_mod

HOME = os.path.expanduser("~")
DEFAULT_WORK_ENV = os.path.join(HOME, ".config", "work", "env")
DEFAULT_WORK_LEDGER = os.path.join(HOME, "projects", "work-ledger")
COMMANDS = ("scan", "remove", "report")
DEFAULT_MIN_IDLE = 48.0
DEFAULT_LOCK_FILE = os.path.join(HOME, ".local", "state", "workspace-gc", "workspace-gc.lock")
DEFAULT_STEP_TIMEOUT = 600.0
DEFAULT_MAX_RUNTIME = 180.0
EXIT_BUSY = 3


def _jobs(value: str) -> int:
    n = int(value)
    if not 1 <= n <= inv_mod.MAX_JOBS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {inv_mod.MAX_JOBS}")
    return n


def _seconds(value: str) -> float:
    n = float(value)
    if n < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return n


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", action="append", dest="roots", metavar="DIR",
                   help="directory to inventory (repeatable; default ~/workspaces)")
    p.add_argument("--main-root", action="append", dest="main_roots", metavar="DIR",
                   help="main-checkout directory: never a removal candidate, also used to "
                        "resolve origin-less clones (repeatable; default ~/projects)")
    p.add_argument("--keep", action="append", default=[], metavar="PATH_OR_GLOB",
                   help="never remove (class C, not inspected); repeatable")
    p.add_argument("--keep-file", default=inv_mod.DEFAULT_KEEP_FILE,
                   help="file with one keep path or glob per line (default %(default)s)")
    p.add_argument("--regenerable", action="append", default=[], metavar="PATTERN",
                   help="extra ignored entry that is safe to lose: a name (any path component), "
                        "a path glob anchored at the checkout root (contains '/', trailing '/' "
                        "= directories only), optionally scoped as REPO:PATTERN (repeatable)")
    p.add_argument("--regenerable-file", default=inv_mod.DEFAULT_REGENERABLE_FILE,
                   help="file with one --regenerable pattern per line (default %(default)s)")
    p.add_argument("--no-fetch", action="store_true",
                   help="do not fetch remotes into a scratch repository to resolve "
                        "'containment unknown'")
    p.add_argument("--work-env", default=DEFAULT_WORK_ENV)
    p.add_argument("--work-ledger", default=DEFAULT_WORK_LEDGER)
    p.add_argument("--no-work", action="store_true", help="do not read work-app items")
    p.add_argument("--no-herdr", action="store_true", help="do not read herdr panes")
    p.add_argument("--no-processes", action="store_true", help="do not read process cwds (lsof)")
    p.add_argument("--no-sizes", action="store_true", help="skip du (faster)")
    p.add_argument("--jobs", type=_jobs, default=8,
                   help=f"checkouts inspected in parallel (1-{inv_mod.MAX_JOBS}, default %(default)s)")
    p.add_argument("--step-timeout", type=_seconds, default=DEFAULT_STEP_TIMEOUT, metavar="SECONDS",
                   help="time limit for inspecting one checkout and for the re-checks before one "
                        "removal; out of time means class C or skip (default %(default)g; 0: none)")
    p.add_argument("--max-runtime", type=_seconds, default=DEFAULT_MAX_RUNTIME, metavar="MINUTES",
                   help="time limit for the whole run: checkouts not inspected by then are class C, "
                        "removals not started by then are skipped and the report is written "
                        "(default %(default)g; 0: none)")
    p.add_argument("--lending-ttl", type=_seconds, default=inv_mod.DEFAULT_LENDING_TTL,
                   metavar="SECONDS",
                   help="reuse the walk for repositories borrowing a clone's objects for this "
                        "long between removals (default %(default)g; 0: walk for every removal)")
    p.add_argument("--lock-file", default=DEFAULT_LOCK_FILE,
                   help="run lock taken by report and every --apply; a second run exits "
                        f"{EXIT_BUSY} at once while it is held (default %(default)s)")


def _idle(p: argparse.ArgumentParser, default: float) -> None:
    p.add_argument("--min-idle-hours", type=float, default=default,
                   help="keep (class D) checkouts with git or directory activity more recent "
                        "than this (default %(default)s; 0 disables)")
    p.add_argument("--min-stale-hours", type=float, default=72.0,
                   help="--apply removes a workspace directory without a checkout (no git "
                        "repository outside .cache/uv, not in use, not keep-listed) once "
                        "nothing in it changed for this long (default %(default)s; 0 disables)")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="workspace-gc", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    scan = sub.add_parser("scan", help="inventory (default command)")
    _common(scan)
    _idle(scan, DEFAULT_MIN_IDLE)
    scan.add_argument("--json", action="store_true", help="print JSON instead of text")
    scan.add_argument("--apply", action="store_true",
                      help="remove class A checkouts, empty workspace directories and stale "
                           "workspace directories without a checkout (see --min-stale-hours), "
                           "prune stale worktree entries")
    rm = sub.add_parser("remove", help="guarded removal of one checkout")
    _common(rm)
    _idle(rm, 0)
    rm.add_argument("path")
    rm.add_argument("--apply", action="store_true", help="actually remove it")
    rp = sub.add_parser("report", help="like scan, but written to files (the scheduled job)")
    _common(rp)
    _idle(rp, DEFAULT_MIN_IDLE)
    rp.add_argument("--out-dir", required=True)
    rp.add_argument("--apply", action="store_true",
                    help="remove like `scan --apply` and report what was removed "
                         "(without it: dry run)")
    rp.add_argument("--work-item", metavar="SLUG",
                    help="also upsert this work-app item with the one-line summary")
    return ap


def _signals(a, sig=None) -> sig_mod.Signals:
    if sig is not None:
        sig.work_env, sig.work_ledger = a.work_env, a.work_ledger
        return sig
    return sig_mod.gather(herdr=not a.no_herdr, processes=not a.no_processes,
                          work=not a.no_work, work_env=a.work_env, work_ledger=a.work_ledger)


def _roots(a) -> list[str]:
    return [os.path.realpath(os.path.expanduser(r)) for r in (a.roots or inv_mod.DEFAULT_ROOTS)]


def _main_roots(a) -> list[str]:
    return [os.path.realpath(os.path.expanduser(r))
            for r in (a.main_roots or inv_mod.DEFAULT_MAIN_ROOTS)]


def _regenerable(a) -> list[str]:
    return inv_mod.load_regenerable(a.regenerable, a.regenerable_file)


def _clock(a) -> budget.RunClock:
    """The run's --max-runtime clock, started when first asked for (main()
    starts it before anything is read)."""
    if getattr(a, "clock", None) is None:
        a.clock = budget.RunClock(a.max_runtime * 60)
    return a.clock


def _build(a, sig, only=None):
    inv = inv_mod.build(_roots(a), sig, main_roots=_main_roots(a), keep=a.keep,
                         keep_file=a.keep_file, regenerable=_regenerable(a),
                         sizes=not a.no_sizes, jobs=a.jobs, only=only,
                         min_idle_hours=a.min_idle_hours, fetch=not a.no_fetch,
                         step_timeout=a.step_timeout, run_deadline=_clock(a).deadline)
    if only is None and not _clock(a).expired():
        # Workspace directories without a checkout: under the run deadline;
        # out of time means they wait for the next run.
        try:
            with budget.step(None, _clock(a).deadline):
                inv.empty_dirs = empties.scan(inv.roots, inv.keep_patterns, sig)
        except budget.StepTimeout:
            inv.empty_dirs = []
            inv.incomplete.append("empty workspace directories not scanned (run time limit)")
        try:
            with budget.step(None, _clock(a).deadline):
                inv.husks = husks.scan(inv, sig, sizes=not a.no_sizes,
                                       min_idle_hours=a.min_idle_hours,
                                       min_stale_hours=a.min_stale_hours)
        except budget.StepTimeout:
            inv.husks = []
            inv.incomplete.append("workspace directories without a checkout not scanned "
                                  "(run time limit)")
    elif only is None:
        inv.incomplete += ["empty workspace directories not scanned (run time limit)",
                           "workspace directories without a checkout not scanned "
                           "(run time limit)"]
    return inv


def _write_atomic(path: str, text: str) -> None:
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _preview_prune(inv) -> None:
    for repo in inv_mod.prune_targets(inv):
        lines = inv_mod.prune_preview(repo)
        if lines:
            inv.prune[repo] = lines


def _apply(a, inv) -> inv_mod.Run:
    """The one apply path, for `scan --apply` and `report --apply`: refuse if
    an in-use source is incomplete; otherwise remove class A (each removal
    re-checked), prune stale worktree entries and remove empty workspace
    directories. Removed checkouts leave inv.checkouts; skipped ones stay in
    class A with the reason. Outcomes also include failed attempted empty/husk
    cleanup; skipped counts those attempts and prune failures as well."""
    run = inv.run = inv_mod.Run(refused=inv.signals.apply_blockers())
    if run.refused:
        _preview_prune(inv)
        return run
    if _clock(a).expired():
        run.stopped = budget.TIME_LIMIT
    targets = inv_mod.prune_targets(inv)
    roots, mains = _roots(a), _main_roots(a)
    # One borrowed-objects walk per --lending-ttl, not one per removed clone.
    lending = inv_mod.LendingCache(roots, mains, inv.keep_patterns, ttl=a.lending_ttl,
                                   timeout=a.step_timeout or None, run_deadline=_clock(a).deadline)
    regenerable = _regenerable(a)
    for co in sorted((c for c in inv.checkouts if c.cls == "A"), key=lambda c: c.path):
        if _clock(a).expired():
            run.stopped = budget.TIME_LIMIT
            run.skipped += 1
            co.reasons.insert(0, "not removed in this run: run time limit reached")
            run.outcomes.append({"path": co.path, "outcome": "skipped: run time limit reached"})
            continue
        try:
            outcome = rm_mod.remove_checkout(co, roots, mains, inv.keep_patterns,
                                             regenerable, fetch=not a.no_fetch,
                                             signals=inv.signals, lending=lending,
                                             step_timeout=a.step_timeout,
                                             run_deadline=_clock(a).deadline)
            run.removed.append(co)
        except rm_mod.Refused as exc:
            run.skipped += 1
            outcome = f"skipped: {exc}"
            co.reasons.insert(0, f"not removed in this run: {exc}")
        run.outcomes.append({"path": co.path, "outcome": outcome})
    inv.checkouts = [c for c in inv.checkouts if c not in run.removed]
    # A clone successfully removed above has no worktree metadata left.
    targets = [r for r in targets if not any(co.path == r for co in run.removed)]
    cleanup_left = lambda: any(e.removable for e in inv.empty_dirs) or \
        any(h.removable or h.stale for h in inv.husks)
    if _clock(a).expired():
        # Out of time: stale worktree entries, empty and stale workspace
        # directories are left for the next run rather than overrun further.
        if targets or cleanup_left():
            run.stopped = budget.TIME_LIMIT
        return run
    for repo in targets:
        if _clock(a).expired():
            run.stopped = budget.TIME_LIMIT
            return run
        try:
            lines = rm_mod.prune(repo)
            if lines:
                inv.prune[repo] = lines
        except rm_mod.GitError as exc:
            run.prune_errors[repo] = str(exc)
            run.skipped += 1
    if _clock(a).expired():
        if cleanup_left():
            run.stopped = budget.TIME_LIMIT
        return run
    attempted_empty = [e for e in inv.empty_dirs if e.removable]
    attempted_husks = [h for h in inv.husks if h.removable or h.stale]
    expired = _clock(a).expired
    empties.remove(inv.empty_dirs, inv.keep_patterns, inv.signals, expired=expired)
    husks.remove(inv.husks, roots, inv.keep_patterns, inv.signals, a.min_idle_hours,
                 a.min_stale_hours, expired=expired)
    if any(e.reason == budget.TIME_LIMIT for e in inv.empty_dirs) or \
            any(h.outcome == budget.TIME_LIMIT for h in inv.husks):
        run.stopped = budget.TIME_LIMIT
    for entry in attempted_empty + attempted_husks:
        if not entry.removed:
            run.skipped += 1
            reason = entry.reason if isinstance(entry, empties.EmptyDir) else entry.outcome
            run.outcomes.append({"path": entry.path, "outcome": "skipped: " + reason})
    return run


def _exit_code(run: inv_mod.Run) -> int:
    return 2 if run.refused else 1 if run.skipped or run.stopped else 0


def cmd_scan(a, sig, out) -> int:
    inv = _build(a, sig)
    if not a.apply:
        _preview_prune(inv)
        out.write(json.dumps(rep.to_json(inv), indent=2) + "\n" if a.json else rep.to_text(inv))
        return 0
    run = _apply(a, inv)
    if run.refused:
        out.write(rep.to_text(inv))
        out.write("REFUSED --apply: in-use signals incomplete: " + rep.escape("; ".join(run.refused)) + "\n")
        return 2
    gone = [e for e in inv.empty_dirs if e.removed]
    if a.json:
        out.write(json.dumps({"removed": run.outcomes, "pruned": inv.prune,
                              "prune_errors": run.prune_errors,
                              "empty_dirs_removed": [e.path for e in gone],
                              "husks_removed": [{"path": h.path, "what": h.removed_what,
                                                 "kb": h.removed_kb}
                                                for h in inv.husks if h.removed],
                              "stopped": run.stopped,
                              "summary": rep.summary_line(inv)}, indent=2) + "\n")
    else:
        for r in run.outcomes:
            if r["outcome"].startswith("removed"):
                out.write(rep.escape(r["outcome"]) + "\n")
            else:
                out.write(f"SKIP {rep.short(r['path'])}: {rep.escape(r['outcome'])}\n")
        for repo, lines in inv.prune.items():
            out.write(f"pruned {len(lines)} stale worktree entr{'y' if len(lines) == 1 else 'ies'} in {rep.short(repo)}\n")
        for repo, error in run.prune_errors.items():
            out.write(f"prune failed {rep.short(repo)}: {rep.escape(error)}\n")
        for e in gone:
            out.write(f"removed empty directory {rep.short(e.path)}\n")
        for h in inv.husks:
            if h.removed:
                out.write(f"removed {h.removed_what} of workspace directory {rep.short(h.path)} "
                          f"({rep.human_kb(h.removed_kb)})\n")
        out.write(f"{len(run.removed)} removed, {run.skipped} skipped, {len(gone)} empty "
                  f"director{'y' if len(gone) == 1 else 'ies'} removed; untouched: "
                  f"{sum(1 for c in inv.checkouts if c.cls != 'A')} checkouts in classes B/C/D\n")
        if run.stopped:
            out.write(f"stopped early: {run.stopped}; the rest is left for the next run\n")
    return _exit_code(run)


def cmd_remove(a, sig, out) -> int:
    target = os.path.realpath(os.path.abspath(os.path.expanduser(a.path)))
    if os.path.islink(os.path.abspath(os.path.expanduser(a.path))):
        out.write(f"REFUSED {rep.escape(a.path)}: is a symlink\n")
        return 1
    roots = _roots(a)
    if not any(target.startswith(r + os.sep) for r in roots):
        out.write(f"REFUSED {rep.escape(target)}: not inside a root ({', '.join(rep.short(r) for r in roots)})\n")
        return 1
    inv = _build(a, sig, only=target)
    if not inv.checkouts:
        out.write(f"REFUSED {rep.escape(target)}: not a git checkout found under the roots\n")
        return 1
    co = inv.checkouts[0]
    desc = f"{rep.short(co.path)} [{co.kind}, class {co.cls}: {inv_mod.CLASS_NAMES[co.cls]}]"
    if co.cls != "A":
        out.write(f"REFUSED {desc}\n" + "".join(f"  - {rep.escape(r)}\n" for r in co.reasons))
        for i, line in enumerate(co.unpushed_commits):
            hint = co.unpushed_hints[i] if i < len(co.unpushed_hints) else ""
            out.write(f"    - {rep.escape(line)}" + (f" [{rep.escape(hint)}]" if hint else "") + "\n")
        return 1
    if not a.apply:
        verb = "git worktree remove" if co.kind == "worktree" else "guarded delete"
        out.write(f"WOULD remove {desc} via {verb}; re-run with --apply\n")
        return 0
    blockers = inv.signals.apply_blockers()
    if blockers:
        out.write(f"REFUSED {desc}: in-use signals incomplete: {rep.escape('; '.join(blockers))}\n")
        return 2
    try:
        out.write(rep.escape(rm_mod.remove_checkout(
            co, roots, _main_roots(a), inv.keep_patterns, _regenerable(a), fetch=not a.no_fetch,
            signals=inv.signals, step_timeout=a.step_timeout,
            run_deadline=_clock(a).deadline)) + "\n")
    except rm_mod.Refused as exc:
        out.write(f"REFUSED {desc}: {rep.escape(exc)}\n")
        return 1
    if co.kind == "worktree" and co.owner_repo:
        try:
            rm_mod.prune(co.owner_repo)
        except rm_mod.GitError as exc:
            out.write(f"prune failed {rep.short(co.owner_repo)}: {rep.escape(exc)}\n")
            return 1
    return 0


def _upsert_item(a, inv, out_dir: str) -> str:
    unavailable = sig_mod.work_available(a.work_env, a.work_ledger)
    if unavailable:
        return f"work item: not updated ({unavailable.detail})"
    report_path = rep.short(os.path.join(out_dir, "latest.txt"))
    refused = bool(inv.run and inv.run.refused)
    what = ("removes class A checkouts, empty workspace directories and stale workspace "
            "directories without a checkout itself") if a.apply \
        else "dry run, nothing removed"
    args = ["upsert", a.work_item, "--title", "workspace-gc report",
            "--project", "agent-stuff", "--repo-url", "https://github.com/ephes/agent-stuff",
            "--stage", "installed", "--owner", "jochen" if refused else "workspace-gc",
            "--next-action", rep.summary_line(inv),
            "--notes", f"Scheduled workspace-gc run on {socket.gethostname()} ({what}); "
                       f"full report in {report_path}.",
            "--checked-at", "now"]
    code, _, err = sig_mod.run_work(a.work_env, a.work_ledger, args)
    if code != 0:
        return f"work item: upsert failed (exit {code}: {err})"
    # The job removes class A itself, so approval requests that earlier
    # versions opened for that are moot.
    code, stdout, err = sig_mod.run_work(a.work_env, a.work_ledger, ["show", "--json", a.work_item])
    if code != 0:
        return f"work item: updated; reading requests failed (exit {code})"
    try:
        requests = json.loads(stdout)["item"].get("requests", [])
    except (ValueError, KeyError, TypeError):
        return "work item: updated; unexpected show output"
    ours = [r for r in requests if r.get("status") == "open" and r.get("kind") == "approval"
            and "workspace-gc" in (r.get("text") or "")]
    for r in ours:
        sig_mod.run_work(a.work_env, a.work_ledger, ["withdraw", str(r["id"])])
    return "work item: updated" + (", moot request withdrawn" if ours else "")


def cmd_report(a, sig, out) -> int:
    out_dir = os.path.realpath(os.path.expanduser(a.out_dir))
    os.makedirs(out_dir, exist_ok=True)
    inv = _build(a, sig)
    if a.apply:
        code = _exit_code(_apply(a, inv))
    else:
        _preview_prune(inv)
        code = 0
    stamp = rep.now_iso()
    _write_atomic(os.path.join(out_dir, "latest.txt"), rep.to_text(inv, stamp))
    _write_atomic(os.path.join(out_dir, "latest.json"),
                  json.dumps(rep.to_json(inv, stamp), indent=2) + "\n")
    msg = f"{stamp} {rep.summary_line(inv)}"
    if a.work_item:
        msg += f"; {_upsert_item(a, inv, out_dir)}"
    out.write(rep.escape(msg) + "\n")
    return code


def main(argv: list[str] | None = None, *, signals: sig_mod.Signals | None = None,
         out=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "scan")
    a = parser().parse_args(argv)
    out = out or sys.stdout
    _clock(a)
    lock = None
    if a.cmd == "report" or getattr(a, "apply", False):
        # Taken before anything is read, so a run never queues behind a hung
        # one; the kernel releases it when this process exits in any way.
        try:
            lock = runlock.acquire(a.lock_file)
        except runlock.Busy as exc:
            out.write(f"{rep.now_iso()} BUSY, nothing done: {rep.escape(exc)}\n")
            return EXIT_BUSY
    try:
        sig = _signals(a, signals)
        return {"scan": cmd_scan, "remove": cmd_remove, "report": cmd_report}[a.cmd](a, sig, out)
    finally:
        if lock is not None:
            lock.release()
