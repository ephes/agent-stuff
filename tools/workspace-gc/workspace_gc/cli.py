"""workspace-gc - inventory agent checkouts and remove the safe ones.

  workspace-gc [scan] [--json] [--apply]   inventory the roots (dry run unless --apply)
  workspace-gc remove [--apply] PATH       guarded removal of one checkout
  workspace-gc report --out-dir DIR        dry run written to DIR/latest.{txt,json}
                                           (for the scheduled job; never applies)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile

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
    p.add_argument("--regenerable", action="append", default=[], metavar="NAME",
                   help="extra ignored file/dir name that is safe to lose (repeatable)")
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


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="workspace-gc", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    scan = sub.add_parser("scan", help="inventory (default command)")
    _common(scan)
    _idle(scan, DEFAULT_MIN_IDLE)
    scan.add_argument("--json", action="store_true", help="print JSON instead of text")
    scan.add_argument("--apply", action="store_true",
                      help="remove class A checkouts and prune stale worktree entries")
    rm = sub.add_parser("remove", help="guarded removal of one checkout")
    _common(rm)
    _idle(rm, 0)
    rm.add_argument("path")
    rm.add_argument("--apply", action="store_true", help="actually remove it")
    rp = sub.add_parser("report", help="write the dry-run report to files (never applies)")
    _common(rp)
    _idle(rp, DEFAULT_MIN_IDLE)
    rp.add_argument("--out-dir", required=True)
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


def _build(a, sig, only=None):
    return inv_mod.build(_roots(a), sig, main_roots=_main_roots(a), keep=a.keep,
                         keep_file=a.keep_file, regenerable=a.regenerable,
                         sizes=not a.no_sizes, jobs=a.jobs, only=only,
                         min_idle_hours=a.min_idle_hours)


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


def cmd_scan(a, sig, out) -> int:
    inv = _build(a, sig)
    targets = inv_mod.prune_targets(inv)
    if not a.apply:
        for repo in targets:
            lines = inv_mod.prune_preview(repo)
            if lines:
                inv.prune[repo] = lines
        out.write(json.dumps(rep.to_json(inv), indent=2) + "\n" if a.json else rep.to_text(inv))
        return 0
    blockers = inv.signals.apply_blockers()
    if blockers:
        out.write(rep.to_text(inv))
        out.write("REFUSED --apply: in-use signals incomplete: " + "; ".join(blockers) + "\n")
        return 2
    results = []
    failed = 0
    roots, mains = _roots(a), _main_roots(a)
    for co in sorted((c for c in inv.checkouts if c.cls == "A"), key=lambda c: c.path):
        try:
            outcome = rm_mod.remove_checkout(co, roots, mains, inv.keep_patterns, a.regenerable)
            results.append({"path": co.path, "outcome": outcome})
        except rm_mod.Refused as exc:
            failed += 1
            results.append({"path": co.path, "outcome": f"skipped: {exc}"})
    pruned = {}
    for repo in targets:
        lines = rm_mod.prune(repo)
        if lines:
            pruned[repo] = lines
    if a.json:
        out.write(json.dumps({"removed": results, "pruned": pruned,
                              "summary": rep.summary_line(inv)}, indent=2) + "\n")
    else:
        for r in results:
            if r["outcome"].startswith("removed"):
                out.write(r["outcome"] + "\n")
            else:
                out.write(f"SKIP {rep.short(r['path'])}: {r['outcome']}\n")
        for repo, lines in pruned.items():
            out.write(f"pruned {len(lines)} stale worktree entr{'y' if len(lines) == 1 else 'ies'} in {rep.short(repo)}\n")
        n_removed = sum(1 for r in results if r["outcome"].startswith("removed"))
        out.write(f"{n_removed} removed, {failed} skipped; untouched: "
                  f"{sum(1 for c in inv.checkouts if c.cls != 'A')} checkouts in classes B/C/D\n")
    return 1 if failed else 0


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
                                         a.regenerable) + "\n")
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
    t = rep.totals(inv)
    removable = t["A"]["count"]
    summary = rep.summary_line(inv)
    report_path = rep.short(os.path.join(out_dir, "latest.txt"))
    args = ["upsert", a.work_item, "--title", "Weekly workspace-gc report",
            "--project", "agent-stuff", "--repo-url", "https://github.com/ephes/agent-stuff",
            "--stage", "installed", "--owner", "jochen" if removable else "workspace-gc",
            "--next-action", summary,
            "--notes", f"Weekly dry run on {socket.gethostname()}; full report in "
                       f"{report_path}. The job never removes anything.",
            "--checked-at", "now"]
    code, _, err = sig_mod.run_work(a.work_env, a.work_ledger, args)
    if code != 0:
        return f"work item: upsert failed (exit {code}: {err})"
    code, stdout, err = sig_mod.run_work(a.work_env, a.work_ledger, ["show", "--json", a.work_item])
    if code != 0:
        return f"work item: updated; reading requests failed (exit {code})"
    try:
        requests = json.loads(stdout)["item"].get("requests", [])
    except (ValueError, KeyError, TypeError):
        return "work item: updated; unexpected show output"
    ours = [r for r in requests if r.get("status") == "open" and r.get("kind") == "approval"
            and "workspace-gc" in (r.get("text") or "")]
    if removable and not ours:
        gb = t["A"]["kb"] / 1024 / 1024
        text = (f"Remove the {removable} class-A checkouts ({gb:.1f} GB) listed in "
                f"{report_path} with workspace-gc --apply?")
        code, _, err = sig_mod.run_work(a.work_env, a.work_ledger,
                                        ["ask", a.work_item, text, "--kind", "approval"])
        return "work item: updated, owner asked" if code == 0 else f"work item: ask failed ({err})"
    if not removable:
        for r in ours:
            sig_mod.run_work(a.work_env, a.work_ledger, ["withdraw", str(r["id"])])
        return "work item: updated" + (", moot request withdrawn" if ours else "")
    return "work item: updated (owner request already open)"


def cmd_report(a, sig, out) -> int:
    out_dir = os.path.realpath(os.path.expanduser(a.out_dir))
    os.makedirs(out_dir, exist_ok=True)
    inv = _build(a, sig)
    for repo in inv_mod.prune_targets(inv):
        lines = inv_mod.prune_preview(repo)
        if lines:
            inv.prune[repo] = lines
    stamp = rep.now_iso()
    _write_atomic(os.path.join(out_dir, "latest.txt"), rep.to_text(inv, stamp))
    _write_atomic(os.path.join(out_dir, "latest.json"),
                  json.dumps(rep.to_json(inv, stamp), indent=2) + "\n")
    msg = f"{stamp} {rep.summary_line(inv)}"
    if a.work_item:
        msg += f"; {_upsert_item(a, inv, out_dir)}"
    out.write(msg + "\n")
    return 0


def main(argv: list[str] | None = None, *, signals: sig_mod.Signals | None = None,
         out=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "scan")
    a = parser().parse_args(argv)
    out = out or sys.stdout
    sig = _signals(a, signals)
    return {"scan": cmd_scan, "remove": cmd_remove, "report": cmd_report}[a.cmd](a, sig, out)
