"""Human and JSON renderings of an inventory."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone

from .inventory import CLASS_NAMES, Inventory

HOME = os.path.expanduser("~")


def short(path: str) -> str:
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + os.sep) else path


def human_kb(kb: int) -> str:
    """A `du -h`-style size: 512K, 27M, 1.3G."""
    if kb >= 1024 * 1024:
        return f"{kb / 1024 / 1024:.1f}G"
    if kb >= 1024:
        return f"{kb / 1024:.0f}M"
    return f"{kb}K"


def totals(inv: Inventory) -> dict[str, dict[str, int]]:
    t = {c: {"count": 0, "kb": 0, "payload_kb": 0} for c in "ABCD"}
    for co in inv.checkouts:
        t[co.cls]["count"] += 1
        t[co.cls]["kb"] += co.size_kb
        t[co.cls]["payload_kb"] += sum(p["kb"] for p in co.payloads)
    return t


def _dirs(n: int) -> str:
    return f"{n} empty director{'y' if n == 1 else 'ies'}"


def summary_line(inv: Inventory) -> str:
    t = totals(inv)
    left = (f"{t['A']['count']} removable ({human_kb(t['A']['kb'])}), "
            f"{t['B']['count']} removable after push, {t['C']['count']} need you")
    run = inv.run
    if run is None:
        n = sum(1 for e in inv.empty_dirs if e.removable)
        return left + (f", {_dirs(n)} removable" if n else "")
    if run.refused:
        return "REFUSED, nothing removed (" + "; ".join(run.refused) + "); " + left
    return (f"removed {len(run.removed)} checkout{'' if len(run.removed) == 1 else 's'} "
            f"({human_kb(sum(c.size_kb for c in run.removed))}) and "
            f"{_dirs(sum(1 for e in inv.empty_dirs if e.removed))}; left: {left}")


def to_json(inv: Inventory, generated_at: str | None = None) -> dict:
    run = inv.run
    return {
        "generated_at": generated_at or now_iso(),
        "host": socket.gethostname(),
        "roots": inv.roots,
        "summary": summary_line(inv),
        "totals": totals(inv),
        "signals": {k: v.to_dict() for k, v in inv.signals.status.items()},
        "apply_blockers": inv.signals.apply_blockers(),
        "checkouts": [co.to_dict() for co in sorted(inv.checkouts, key=lambda c: (c.cls, c.path))],
        "prune": inv.prune,
        "empty_dirs": [e.to_dict() for e in inv.empty_dirs],
        "husks": [h.to_dict() for h in inv.husks],
        "mode": "dry-run" if run is None else "refused" if run.refused else "applied",
        "removed": [co.to_dict() for co in run.removed] if run else [],
        "removed_kb": sum(c.size_kb for c in run.removed) if run else 0,
        "skipped": [o for o in run.outcomes if not o["outcome"].startswith("removed")] if run else [],
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _checkout_line(co) -> str:
    bits = [co.kind]
    if co.branch:
        bits.append(co.branch)
    if co.size_kb:
        bits.append(human_kb(co.size_kb))
    if co.last_commit:
        bits.append(f"last commit {co.last_commit}")
    return f"- {short(co.path)} [{', '.join(bits)}]"


def to_text(inv: Inventory, generated_at: str | None = None) -> str:
    out = []
    w = out.append
    run = inv.run
    applied = run is not None and not run.refused
    mode = "dry run" if run is None else "run, removals applied" if applied \
        else "run REFUSED, nothing removed"
    w(f"workspace-gc {mode} - {generated_at or now_iso()} on {socket.gethostname()}")
    w("roots: " + ", ".join(short(r) for r in inv.roots))
    w("signals: " + "; ".join(f"{k} {v.status}{' (' + v.detail + ')' if v.detail else ''}"
                              for k, v in sorted(inv.signals.status.items())))
    blockers = inv.signals.apply_blockers()
    if blockers:
        w(("REFUSED, in-use signals incomplete: " if run else "--apply would refuse: ")
          + "; ".join(blockers))
    w("")
    w("summary: " + summary_line(inv))
    if applied:
        gone = [e for e in inv.empty_dirs if e.removed]
        w("")
        w(f"## Removed in this run ({len(run.removed)} checkout"
          f"{'' if len(run.removed) == 1 else 's'}, "
          f"{human_kb(sum(c.size_kb for c in run.removed))}; {_dirs(len(gone))})")
        w("")
        for co in sorted(run.removed, key=lambda x: x.path):
            w(_checkout_line(co))
        for e in gone:
            w(f"- {short(e.path)} [empty directory]")
        if not run.removed and not gone:
            w("- nothing")
        w("")
        w("## What remains")
    t = totals(inv)
    w("")
    w("| Class | Meaning | Count | Disk | of which regenerable payloads |")
    w("|---|---|---|---|---|")
    for c in "ABCD":
        w(f"| {c} | {CLASS_NAMES[c]} | {t[c]['count']} | {human_kb(t[c]['kb'])} "
          f"| {human_kb(t[c]['payload_kb'])} |")
    for c in "ABCD":
        cos = sorted((x for x in inv.checkouts if x.cls == c), key=lambda x: x.path)
        if not cos:
            continue
        w("")
        w(f"## {c} - {CLASS_NAMES[c]} ({len(cos)})")
        w("")
        for co in cos:
            w(_checkout_line(co))
            for r in co.reasons:
                w(f"  - {r}")
            for i, line in enumerate(co.unpushed_commits if c in "BC" else []):
                hint = co.unpushed_hints[i] if i < len(co.unpushed_hints) else ""
                w(f"    - {line}" + (f" [{hint}]" if hint else ""))
            if co.unpushed > len(co.unpushed_commits) and co.unpushed_commits and c in "BC":
                w(f"    - ... ({co.unpushed - len(co.unpushed_commits)} more)")
            if co.payloads:
                w("  - payloads: " + ", ".join(f"{p['path']} {human_kb(p['kb'])}"
                                               for p in sorted(co.payloads, key=lambda p: -p["kb"])))
            for n in co.notes:
                w(f"  - note: {n}")
    left = [e for e in inv.empty_dirs if not e.removed]
    if left:
        w("")
        w(f"## Empty workspace directories ({sum(1 for e in left if e.removable)} removable, "
          f"{sum(1 for e in left if not e.removable)} kept)")
        w("")
        for e in left:
            w(f"- {short(e.path)}" + (f" - kept: {e.reason}" if e.reason else ""))
    if inv.husks:
        w("")
        w(f"## Workspace directories without a checkout ({len(inv.husks)}, "
          f"{human_kb(sum(h.kb for h in inv.husks))}, of which workspace-level caches "
          f"{human_kb(sum(h.payload_kb for h in inv.husks))}; never removed by this tool)")
        w("")
        for h in sorted(inv.husks, key=lambda x: -x.kb):
            w(f"- {short(h.path)} [{human_kb(h.kb)}, caches {human_kb(h.payload_kb)}, "
              f"{h.files} files]" + (f" - kept: {h.kept}" if h.kept else ""))
            if h.git_dirs:
                w("  - contains git repositories: " + ", ".join(h.git_dirs[:5])
                  + (f" (+{len(h.git_dirs) - 5} more)" if len(h.git_dirs) > 5 else ""))
            ents = sorted(h.entries, key=lambda e: -e["kb"])
            if ents:
                w("  - " + ", ".join(f"{e['path']} {human_kb(e['kb'])}"
                                     + (" (cache)" if e["payload"] else "") for e in ents[:8])
                  + (f", ... (+{len(ents) - 8} more)" if len(ents) > 8 else ""))
            if h.note:
                w(f"  - note: {h.note}")
    if inv.prune:
        w("")
        w("## Stale worktree entries" + (" (pruned)" if applied else ""))
        w("")
        for repo, lines in sorted(inv.prune.items()):
            w(f"- {short(repo)}: {len(lines)} entr{'y' if len(lines) == 1 else 'ies'}")
            for ln in lines[:5]:
                w(f"  - {ln}")
            if len(lines) > 5:
                w(f"  - ... ({len(lines) - 5} more)")
    w("")
    w("Only class A checkouts and empty top-level workspace directories are ever removed, and "
      "only with --apply (the scheduled job runs `report --apply`) or `workspace-gc remove "
      "--apply <path>`. B needs a push first; C and D are never touched.")
    return "\n".join(out) + "\n"
