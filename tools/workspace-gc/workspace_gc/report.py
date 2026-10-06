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


def summary_line(inv: Inventory) -> str:
    t = totals(inv)
    gb = t["A"]["kb"] / 1024 / 1024
    return (f"{t['A']['count']} removable ({gb:.1f} GB), "
            f"{t['B']['count']} removable after push, {t['C']['count']} need you")


def to_json(inv: Inventory, generated_at: str | None = None) -> dict:
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
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def to_text(inv: Inventory, generated_at: str | None = None) -> str:
    out = []
    w = out.append
    w(f"workspace-gc dry run - {generated_at or now_iso()} on {socket.gethostname()}")
    w("roots: " + ", ".join(short(r) for r in inv.roots))
    w("signals: " + "; ".join(f"{k} {v.status}{' (' + v.detail + ')' if v.detail else ''}"
                              for k, v in sorted(inv.signals.status.items())))
    blockers = inv.signals.apply_blockers()
    if blockers:
        w("--apply would refuse: " + "; ".join(blockers))
    w("")
    w("summary: " + summary_line(inv))
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
            bits = [co.kind]
            if co.branch:
                bits.append(co.branch)
            if co.size_kb:
                bits.append(human_kb(co.size_kb))
            if co.last_commit:
                bits.append(f"last commit {co.last_commit}")
            w(f"- {short(co.path)} [{', '.join(bits)}]")
            for r in co.reasons:
                w(f"  - {r}")
            for line in co.unpushed_commits if c in "BC" else []:
                w(f"    - {line}")
            if co.unpushed > len(co.unpushed_commits) and co.unpushed_commits and c in "BC":
                w(f"    - ... ({co.unpushed - len(co.unpushed_commits)} more)")
            if co.payloads:
                w("  - payloads: " + ", ".join(f"{p['path']} {human_kb(p['kb'])}"
                                               for p in sorted(co.payloads, key=lambda p: -p["kb"])))
            for n in co.notes:
                w(f"  - note: {n}")
    if inv.prune:
        w("")
        w("## Stale worktree entries")
        w("")
        for repo, lines in sorted(inv.prune.items()):
            w(f"- {short(repo)}: {len(lines)} entr{'y' if len(lines) == 1 else 'ies'}")
            for ln in lines[:5]:
                w(f"  - {ln}")
            if len(lines) > 5:
                w(f"  - ... ({len(lines) - 5} more)")
    w("")
    w("Only class A is ever removed, and only with --apply (or `workspace-gc remove "
      "--apply <path>`). B needs a push first; C and D are never touched.")
    return "\n".join(out) + "\n"
