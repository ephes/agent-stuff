"""Assemble a bounded review bundle from the working tree's git state. Because Pi
runs with --no-tools, this bundle is the entire review surface, so its contents
are explicit and its omissions are recorded (never silent)."""
import os
import subprocess
from dataclasses import dataclass, field


@dataclass
class BundleResult:
    path: str
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _truncate(text, limit, label, truncations):
    if len(text.encode()) <= limit:
        return text
    cut = text.encode()[:limit].decode(errors="ignore")
    truncations.append({"section": label, "kept_bytes": len(cut.encode())})
    return cut + f"\n... [truncated {label} at {limit} bytes] ...\n"


def build_bundle(repo, out_path, *, max_file_size, max_diff_bytes_per_file,
                 max_bundle_bytes, staged_only=False):
    skipped, truncations = [], []
    sections = []  # (priority, title, body) — lower priority dropped first

    diffstat = _git(repo, "diff", "--stat", "HEAD")
    sections.append((0, "Diffstat", diffstat or "(no tracked changes)"))

    staged = _git(repo, "diff", "--cached")
    if staged.strip():
        staged = _truncate(staged, max_diff_bytes_per_file, "staged diff", truncations)
        sections.append((1, "Staged diff", staged))

    if not staged_only:
        unstaged = _git(repo, "diff")
        if unstaged.strip():
            unstaged = _truncate(unstaged, max_diff_bytes_per_file, "unstaged diff", truncations)
            sections.append((1, "Unstaged diff", unstaged))

    # Untracked files (porcelain '??'); renamed/deleted noted via name-status.
    porcelain = _git(repo, "status", "--porcelain")
    untracked_bodies, notes = [], []
    for line in porcelain.splitlines():
        code, path = line[:2], line[3:]
        if code == "??":
            full = os.path.join(repo, path)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > max_file_size:
                skipped.append({"path": path, "reason": "size", "size": size})
                continue
            try:
                with open(full, "rb") as fh:
                    raw = fh.read()
                if b"\x00" in raw:
                    notes.append(f"- {path}: untracked BINARY (omitted)")
                    continue
                untracked_bodies.append(f"### {path}\n```\n{raw.decode(errors='replace')}\n```")
            except OSError:
                continue
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
            notes.append(f"- {line.split(chr(9))[-1]}: BINARY (no content)")

    if untracked_bodies:
        sections.append((2, "Untracked files", "\n\n".join(untracked_bodies)))
    if notes:
        sections.append((3, "Renamed / deleted / binary", "\n".join(notes)))

    # Render, dropping lowest-priority sections if over the total cap.
    def render(secs):
        parts = ["# Review bundle\n"]
        for _, title, body in secs:
            parts.append(f"\n## {title}\n\n{body}\n")
        if skipped:
            parts.append("\n## Skipped for size\n\n" +
                         "\n".join(f"- {s['path']} ({s['size']} bytes)" for s in skipped) + "\n")
        return "".join(parts)

    secs = sorted(sections, key=lambda s: s[0])
    text = render(secs)
    while len(text.encode()) > max_bundle_bytes and len(secs) > 1:
        dropped = secs.pop()  # highest priority number = lowest importance
        truncations.append({"section": dropped[1], "dropped": True})
        text = render(secs)

    with open(out_path, "w") as fh:
        fh.write(text)
    return BundleResult(path=out_path, skipped_files=skipped, truncations=truncations)
