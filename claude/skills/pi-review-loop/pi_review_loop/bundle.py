"""Assemble a bounded review bundle from the working tree's git state. Because Pi
runs with --no-tools, this bundle is the entire review surface, so its contents
are explicit and its omissions are recorded (never silent)."""
import os
import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class BundleResult:
    path: str
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)
    has_changes: bool = False


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _diff_chunk_path(chunk):
    """Extract the file path from a single diff chunk. The `diff --git a/X b/X`
    header is ambiguous for paths with spaces, so prefer the `+++ b/<path>` /
    `--- a/<path>` lines, whose path runs to end of line. Strips git's quoting
    if present. Falls back to the header's first token, then '?'."""
    for pat in (r"^\+\+\+ b/(.+)$", r"^--- a/(.+)$"):
        m = re.search(pat, chunk, re.M)
        if m:
            p = m.group(1).rstrip()
            return p[1:-1] if p.startswith('"') and p.endswith('"') else p
    m = re.match(r"diff --git a/(\S+)", chunk)
    return m.group(1) if m else "?"


def _truncate_diff_per_file(diff_text, limit, label, truncations):
    """Split a unified diff into per-file chunks and truncate EACH chunk over
    `limit`, recording the path of every truncated file. This guarantees a
    multi-file diff never silently drops later files."""
    if not diff_text.strip():
        return diff_text
    chunks = re.split(r"(?=^diff --git )", diff_text, flags=re.M)
    out = []
    for chunk in chunks:
        if not chunk:
            continue
        if len(chunk.encode()) > limit:
            path = _diff_chunk_path(chunk)
            cut = chunk.encode()[:limit].decode(errors="ignore")
            truncations.append({"section": label, "path": path,
                                "kept_bytes": len(cut.encode())})
            chunk = cut + f"\n... [truncated {path} diff at {limit} bytes] ...\n"
        out.append(chunk)
    return "".join(out)


def build_bundle(repo, out_path, *, max_file_size, max_diff_bytes_per_file,
                 max_bundle_bytes, staged_only=False):
    skipped, truncations = [], []
    sections = []  # (priority, title, body) — lower priority dropped first

    diffstat = _git(repo, "diff", "--stat", "HEAD")
    sections.append((0, "Diffstat", diffstat or "(no tracked changes)"))

    staged = _git(repo, "diff", "--cached")
    if staged.strip():
        staged = _truncate_diff_per_file(staged, max_diff_bytes_per_file, "staged diff", truncations)
        sections.append((1, "Staged diff", staged))

    if not staged_only:
        unstaged = _git(repo, "diff")
        if unstaged.strip():
            unstaged = _truncate_diff_per_file(unstaged, max_diff_bytes_per_file, "unstaged diff", truncations)
            sections.append((1, "Unstaged diff", unstaged))

    # core.quotePath=false stops octal-escaping of non-ASCII; we still strip the
    # surrounding quotes git adds for names with spaces.
    porcelain = _git(
        repo, "-c", "core.quotePath=false",
        "status", "--porcelain", "--untracked-files=all",
    )
    untracked_bodies, notes = [], []
    for line in porcelain.splitlines():
        code, raw_path = line[:2], line[3:]
        if code != "??":
            continue
        path = raw_path[1:-1] if raw_path.startswith('"') and raw_path.endswith('"') else raw_path
        full = os.path.join(repo, path)
        try:
            size = os.path.getsize(full)
        except OSError:
            skipped.append({"path": path, "reason": "unreadable"})  # never silent
            continue
        if size > max_file_size:
            skipped.append({"path": path, "reason": "size", "size": size})
            continue
        try:
            with open(full, "rb") as fh:
                raw = fh.read()
        except OSError:
            skipped.append({"path": path, "reason": "unreadable"})
            continue
        if b"\x00" in raw:
            skipped.append({"path": path, "reason": "binary"})
            continue
        untracked_bodies.append(f"### {path}\n```\n{raw.decode(errors='replace')}\n```")
    name_status = _git(repo, "diff", "--name-status", "HEAD")
    for line in name_status.splitlines():
        tag = line.split("\t", 1)[0]
        if tag.startswith("R"):
            notes.append(f"- {line} (renamed)")
        elif tag.startswith("D"):
            notes.append(f"- {line} (deleted)")
    numstat = _git(repo, "diff", "--numstat", "HEAD")
    for line in numstat.splitlines():
        if line.startswith("-\t-\t"):
            skipped.append({"path": line.split(chr(9))[-1], "reason": "binary-diff"})

    if untracked_bodies:
        sections.append((2, "Untracked files", "\n\n".join(untracked_bodies)))
    if notes:
        sections.append((3, "Renamed / deleted", "\n".join(notes)))

    # Render, dropping lowest-priority sections if over the total cap.
    def render(secs):
        parts = ["# Review bundle\n"]
        for _, title, body in secs:
            parts.append(f"\n## {title}\n\n{body}\n")
        if skipped:
            lines_ = []
            for s in skipped:
                detail = s.get("reason", "skipped")
                if "size" in s:
                    detail += f", {s['size']} bytes"
                lines_.append(f"- {s['path']} ({detail})")
            parts.append("\n## Skipped files\n\n" + "\n".join(lines_) + "\n")
        return "".join(parts)

    secs = sorted(sections, key=lambda s: s[0])
    text = render(secs)
    # Stop at 1 section: Diffstat is always kept even if still over cap — better
    # an over-cap bundle than a silently empty one. Never lower this to >= 1.
    while len(text.encode()) > max_bundle_bytes and len(secs) > 1:
        dropped = secs.pop()  # highest priority number = lowest importance
        truncations.append({"section": dropped[1], "dropped": True})
        text = render(secs)

    has_changes = bool(staged.strip() or (not staged_only and unstaged.strip()) or
                       untracked_bodies or notes or skipped)

    with open(out_path, "w") as fh:
        fh.write(text)
    return BundleResult(path=out_path, skipped_files=skipped,
                        truncations=truncations, has_changes=has_changes)
