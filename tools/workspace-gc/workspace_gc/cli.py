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

from . import empties
from . import husks
from . import inventory as inv_mod
from . import remove as rm_mod
from . import report as rep
from . import signals as sig_mod

HOME = os.path.expanduser("~")
DEFAULT_WORK_ENV = os.path.join(HOME, ".config", "work", "env")
DEFAULT_WORK_LEDGER = os.path.join(HOME, "projects", "work-ledger")
COMMANDS = ("scan", "remove", "report")
DEFAULT_MIN_IDLE = 48.0


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
    p.add_argument("--jobs", type=int, default=8)


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


def _build(a, sig, only=None):
    inv = inv_mod.build(_roots(a), sig, main_roots=_main_roots(a), keep=a.keep,
                         keep_file=a.keep_file, regenerable=_regenerable(a),
                         sizes=not a.no_sizes, jobs=a.jobs, only=only,
                         min_idle_hours=a.min_idle_hours, fetch=not a.no_fetch)
    if only is None:
        inv.empty_dirs = empties.scan(inv.roots, inv.keep_patterns, sig)
        inv.husks = husks.scan(inv, sig, sizes=not a.no_sizes,
                               min_idle_hours=a.min_idle_hours,
                               min_stale_hours=a.min_stale_hours)
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
    class A with the reason."""
    run = inv.run = inv_mod.Run(refused=inv.signals.apply_blockers())
    if run.refused:
        _preview_prune(inv)
        return run
    targets = inv_mod.prune_targets(inv)
    roots, mains = _roots(a), _main_roots(a)
    for co in sorted((c for c in inv.checkouts if c.cls == "A"), key=lambda c: c.path):
        try:
            outcome = rm_mod.remove_checkout(co, roots, mains, inv.keep_patterns,
                                             _regenerable(a), fetch=not a.no_fetch)
            run.removed.append(co)
        except rm_mod.Refused as exc:
            run.skipped += 1
            outcome = f"skipped: {exc}"
            co.reasons.insert(0, f"not removed in this run: {exc}")
        run.outcomes.append({"path": co.path, "outcome": outcome})
    inv.checkouts = [c for c in inv.checkouts if c not in run.removed]
    for repo in targets:
        lines = rm_mod.prune(repo)
        if lines:
            inv.prune[repo] = lines
    empties.remove(inv.empty_dirs, inv.keep_patterns, inv.signals)
    husks.remove(inv.husks, roots, inv.keep_patterns, inv.signals, a.min_idle_hours,
                 a.min_stale_hours)
    return run


def _exit_code(run: inv_mod.Run) -> int:
    return 2 if run.refused else 1 if run.skipped else 0


def cmd_scan(a, sig, out) -> int:
    inv = _build(a, sig)
    if not a.apply:
        _preview_prune(inv)
        out.write(json.dumps(rep.to_json(inv), indent=2) + "\n" if a.json else rep.to_text(inv))
        return 0
    run = _apply(a, inv)
    if run.refused:
        out.write(rep.to_text(inv))
        out.write("REFUSED --apply: in-use signals incomplete: " + "; ".join(run.refused) + "\n")
        return 2
    gone = [e for e in inv.empty_dirs if e.removed]
    if a.json:
        out.write(json.dumps({"removed": run.outcomes, "pruned": inv.prune,
                              "empty_dirs_removed": [e.path for e in gone],
                              "husks_removed": [{"path": h.path, "what": h.removed_what,
                                                 "kb": h.removed_kb}
                                                for h in inv.husks if h.removed],
                              "summary": rep.summary_line(inv)}, indent=2) + "\n")
    else:
        for r in run.outcomes:
            if r["outcome"].startswith("removed"):
                out.write(r["outcome"] + "\n")
            else:
                out.write(f"SKIP {rep.short(r['path'])}: {r['outcome']}\n")
        for repo, lines in inv.prune.items():
            out.write(f"pruned {len(lines)} stale worktree entr{'y' if len(lines) == 1 else 'ies'} in {rep.short(repo)}\n")
        for e in gone:
            out.write(f"removed empty directory {e.path}\n")
        for h in inv.husks:
            if h.removed:
                out.write(f"removed {h.removed_what} of workspace directory {h.path} "
                          f"({rep.human_kb(h.removed_kb)})\n")
        out.write(f"{len(run.removed)} removed, {run.skipped} skipped, {len(gone)} empty "
                  f"director{'y' if len(gone) == 1 else 'ies'} removed; untouched: "
                  f"{sum(1 for c in inv.checkouts if c.cls != 'A')} checkouts in classes B/C/D\n")
    return _exit_code(run)


def cmd_remove(a, sig, out) -> int:
    target = os.path.realpath(os.path.abspath(os.path.expanduser(a.path)))
    if os.path.islink(os.path.abspath(os.path.expanduser(a.path))):
        out.write(f"REFUSED {a.path}: is a symlink\n")
        return 1
    roots = _roots(a)
    if not any(target.startswith(r + os.sep) for r in roots):
        out.write(f"REFUSED {target}: not inside a root ({', '.join(rep.short(r) for r in roots)})\n")
        return 1
    inv = _build(a, sig, only=target)
    if not inv.checkouts:
        out.write(f"REFUSED {target}: not a git checkout found under the roots\n")
        return 1
    co = inv.checkouts[0]
    desc = f"{rep.short(co.path)} [{co.kind}, class {co.cls}: {inv_mod.CLASS_NAMES[co.cls]}]"
    if co.cls != "A":
        out.write(f"REFUSED {desc}\n" + "".join(f"  - {r}\n" for r in co.reasons))
        for i, line in enumerate(co.unpushed_commits):
            hint = co.unpushed_hints[i] if i < len(co.unpushed_hints) else ""
            out.write(f"    - {line}" + (f" [{hint}]" if hint else "") + "\n")
        return 1
    if not a.apply:
        verb = "git worktree remove" if co.kind == "worktree" else "guarded delete"
        out.write(f"WOULD remove {desc} via {verb}; re-run with --apply\n")
        return 0
    blockers = inv.signals.apply_blockers()
    if blockers:
        out.write(f"REFUSED {desc}: in-use signals incomplete: {'; '.join(blockers)}\n")
        return 2
    try:
        out.write(rm_mod.remove_checkout(co, roots, _main_roots(a), inv.keep_patterns,
                                         _regenerable(a), fetch=not a.no_fetch) + "\n")
    except rm_mod.Refused as exc:
        out.write(f"REFUSED {desc}: {exc}\n")
        return 1
    if co.kind == "worktree" and co.owner_repo:
        rm_mod.prune(co.owner_repo)
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
    out.write(msg + "\n")
    return code


def main(argv: list[str] | None = None, *, signals: sig_mod.Signals | None = None,
         out=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "scan")
    a = parser().parse_args(argv)
    out = out or sys.stdout
    sig = _signals(a, signals)
    return {"scan": cmd_scan, "remove": cmd_remove, "report": cmd_report}[a.cmd](a, sig, out)
