"""Assemble a bounded, redacted review bundle from the working tree."""
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field

from .redact import is_secret_path, redact_diff, redact_text


BASELINE_MESSAGE = "claude-review-loop review baseline"
BASELINE_IDENTITY = {
    "GIT_AUTHOR_NAME": "claude-review-loop",
    "GIT_AUTHOR_EMAIL": "claude-review-loop@localhost",
    "GIT_COMMITTER_NAME": "claude-review-loop",
    "GIT_COMMITTER_EMAIL": "claude-review-loop@localhost",
}


@dataclass
class BundleResult:
    path: str
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)
    redactions: list = field(default_factory=list)
    baseline_ref: str = None
    baseline_commit: str = None
    has_changes: bool = False


def _git(repo, *args, replacement_log, env_extra=None, input_bytes=None):
    env = dict(os.environ, LC_ALL="C", LANG="C")
    if env_extra:
        env.update(env_extra)
    completed = subprocess.run(["git", "--no-optional-locks", *args],
                               cwd=repo, check=True, input=input_bytes,
                               capture_output=True, env=env)
    # Decode explicitly after byte capture: subprocess text mode performs
    # universal-newline conversion, which would turn repository-controlled lone
    # CR bytes into structural line breaks before redaction.
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        replacement_log.append("git " + " ".join(args))
        return completed.stdout.decode("utf-8", errors="replace")


def _diff(repo, *args, replacement_log):
    """Run git diff without invoking configured external/textconv drivers."""
    return _git(
        repo,
        "-c", "diff.noprefix=false",
        "-c", "diff.mnemonicPrefix=false",
        "-c", "diff.suppressBlankEmpty=false",
        "-c", "color.ui=false",
        "diff", "--default-prefix", "--no-color",
        "--no-ext-diff", "--no-textconv", *args,
        replacement_log=replacement_log,
    )


def _resolve_tree(repo, ref, *, replacement_log):
    """Resolve a caller-supplied baseline ref to the tree object it names."""
    try:
        out = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{tree}}",
                   replacement_log=replacement_log)
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"baseline ref does not name a tree in this repository: {ref}"
        ) from exc
    tree = out.strip()
    if not tree:
        raise ValueError(
            f"baseline ref does not name a tree in this repository: {ref}"
        )
    return tree


def _snapshot_tree(repo, index_path, include_paths, *, replacement_log):
    """Write a tree object for the reviewed content.

    Uses a private index file so the caller's index, worktree, and refs are
    never touched. Only `include_paths` - the tracked changes and the untracked
    files the bundle accepted - enter the tree, so a skipped secret-looking,
    oversized, or binary file is not written into the object store either.
    """
    env_extra = {"GIT_INDEX_FILE": os.path.abspath(index_path)}
    _git(repo, "read-tree", "HEAD",
         replacement_log=replacement_log, env_extra=env_extra)
    paths = sorted(set(include_paths))
    if paths:
        # `:(literal)` stops a filename containing pathspec magic (`*`, `:`,
        # a leading `!`) from matching anything other than itself.
        payload = b"".join(f":(literal){p}".encode() + b"\0" for p in paths)
        _git(repo, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
             replacement_log=replacement_log, env_extra=env_extra,
             input_bytes=payload)
    return _git(repo, "write-tree",
                replacement_log=replacement_log, env_extra=env_extra).strip()


def _commit_snapshot(repo, tree, *, replacement_log):
    """Commit a snapshot tree as a dangling commit.

    No ref points at it, so it stays out of the caller's history and is
    collected by a later `git gc`. A fixed identity keeps it from failing in a
    repository without a configured user and from being mistaken for the
    caller's own work.
    """
    return _git(repo, "commit-tree", tree, "-p", "HEAD", "-m", BASELINE_MESSAGE,
                replacement_log=replacement_log,
                env_extra=BASELINE_IDENTITY).strip()


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
                 max_bundle_bytes, staged_only=False, context_files=None,
                 max_context_file_size=262144, baseline_ref=None,
                 record_baseline=False, index_path=None):
    """Assemble the review bundle from the worktree.

    Without `baseline_ref` the bundle is the whole worktree delta against
    `HEAD`. With one, it holds only what changed since that baseline snapshot -
    the repair delta a re-review round is meant to inspect - so later rounds do
    not re-read the whole slice and rediscover unrelated concerns in it.
    """
    if baseline_ref is not None and staged_only:
        raise ValueError("staged_only cannot be combined with baseline_ref")
    skipped, truncations, redactions = [], [], []
    decoding_replacements = []
    sections = []  # (priority, title, body) - higher numbers are dropped first
    context_titles = set()
    delta_mode = baseline_ref is not None
    included_untracked = []

    # core.quotePath=false stops octal-escaping of non-ASCII; we still strip the
    # surrounding quotes git adds for names with spaces.
    porcelain = _git(
        repo, "-c", "core.quotePath=false",
        "status", "--porcelain", "--untracked-files=all",
        replacement_log=decoding_replacements,
    )
    untracked_bodies, notes = [], []
    for line in porcelain.split("\n"):
        code, raw_path = line[:2], line[3:]
        if code != "??":
            continue
        path = raw_path[1:-1] if raw_path.startswith('"') and raw_path.endswith('"') else raw_path
        if is_secret_path(path):
            redactions.append({"path": path, "section": "untracked file"})
            untracked_bodies.append(
                f"### {path}\n\n[redacted: secret-looking file not sent]"
            )
            continue
        full = os.path.join(repo, path)
        try:
            mode = os.lstat(full).st_mode
        except OSError:
            skipped.append({"path": path, "reason": "unreadable"})
            continue
        if stat.S_ISLNK(mode):
            skipped.append({"path": path, "reason": "symlink"})
            continue
        if not stat.S_ISREG(mode):
            skipped.append({"path": path, "reason": "not-a-regular-file"})
            continue
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
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            decoded = raw.decode("utf-8", errors="replace")
            truncations.append({
                "section": "untracked file", "path": path,
                "reason": "non-UTF-8 bytes replaced",
            })
        content, changed = redact_text(decoded)
        if changed:
            redactions.append({"path": path, "section": "untracked file"})
        included_untracked.append(path)
        untracked_bodies.append(f"### {path}\n```\n{content}\n```")
    # Resolve the caller's baseline before writing any object, so a bad ref
    # fails without leaving anything behind in the repository.
    base_tree = _resolve_tree(repo, baseline_ref,
                              replacement_log=decoding_replacements) if delta_mode else None

    baseline_commit = None
    snapshot = None
    if delta_mode or record_baseline:
        tracked_changed = [p for p in _diff(
            repo, "--name-only", "-z", "HEAD",
            replacement_log=decoding_replacements).split("\0") if p]
        index_path = index_path or os.path.join(
            os.path.dirname(os.path.abspath(out_path)), "baseline.index")
        try:
            snapshot = _snapshot_tree(
                repo, index_path, tracked_changed + included_untracked,
                replacement_log=decoding_replacements)
        finally:
            # Scratch state: the reviewer can read the run directory, and the
            # index has no business being visible there after the tree exists.
            try:
                os.unlink(index_path)
            except OSError:
                pass
        if record_baseline:
            baseline_commit = _commit_snapshot(
                repo, snapshot, replacement_log=decoding_replacements)

    if delta_mode:
        compare = (base_tree, snapshot)
        diffstat = _diff(repo, "--stat", *compare,
                         replacement_log=decoding_replacements)
        diffstat_title = "Diffstat (since the previous review)"
        sections.append((0, diffstat_title,
                         diffstat or "(nothing changed since the previous review)"))
        delta = _diff(repo, *compare, replacement_log=decoding_replacements)
        if delta.strip():
            delta, paths = redact_diff(delta)
            redactions.extend({"path": p, "section": "repair delta"} for p in paths)
            delta = _truncate_diff_per_file(delta, max_diff_bytes_per_file,
                                            "repair delta", truncations)
            sections.append((1, "Changes since the previous review", delta))
        # No separate untracked section: a file created since the baseline is
        # already in the delta as an added file, and one that has not changed
        # since then is deliberately out of this round's scope.
    else:
        compare = ("HEAD",)
        diffstat = _diff(repo, "--stat", "HEAD",
                         replacement_log=decoding_replacements)
        diffstat_title = "Diffstat"
        sections.append((0, diffstat_title, diffstat or "(no tracked changes)"))

        staged = _diff(repo, "--cached", replacement_log=decoding_replacements)
        if staged.strip():
            staged, paths = redact_diff(staged)
            redactions.extend({"path": p, "section": "staged diff"} for p in paths)
            staged = _truncate_diff_per_file(staged, max_diff_bytes_per_file, "staged diff", truncations)
            sections.append((1, "Staged diff", staged))

        if not staged_only:
            unstaged = _diff(repo, replacement_log=decoding_replacements)
            if unstaged.strip():
                unstaged, paths = redact_diff(unstaged)
                redactions.extend({"path": p, "section": "unstaged diff"} for p in paths)
                unstaged = _truncate_diff_per_file(unstaged, max_diff_bytes_per_file, "unstaged diff", truncations)
                sections.append((1, "Unstaged diff", unstaged))

        if untracked_bodies:
            sections.append((2, "Untracked files", "\n\n".join(untracked_bodies)))

    name_status = _diff(repo, "--name-status", *compare,
                        replacement_log=decoding_replacements)
    for line in name_status.split("\n"):
        tag = line.split("\t", 1)[0]
        if tag.startswith("R"):
            notes.append(f"- {line} (renamed)")
        elif tag.startswith("D"):
            notes.append(f"- {line} (deleted)")
    numstat = _diff(repo, "--numstat", *compare,
                    replacement_log=decoding_replacements)
    for line in numstat.split("\n"):
        if line.startswith("-\t-\t"):
            skipped.append({"path": line.split(chr(9))[-1], "reason": "binary-diff"})
    if notes:
        sections.append((3, "Renamed / deleted", "\n".join(notes)))
    if decoding_replacements:
        truncations.append({
            "section": "Git output",
            "reason": "non-UTF-8 bytes replaced",
            "commands": sorted(set(decoding_replacements)),
        })
    if skipped:
        lines_ = []
        for item in skipped:
            detail = item.get("reason", "skipped")
            if "size" in item:
                detail += f", {item['size']} bytes"
            lines_.append(f"- {item['path']} ({detail})")
        sections.append((4, "Skipped files", "\n".join(lines_)))

    for context_index, context_path in enumerate(context_files or [], start=1):
        if is_secret_path(context_path):
            raise OSError(
                f"explicit context file has a secret-looking path: {context_path}"
            )
        try:
            context_stat = os.lstat(context_path)
        except OSError as exc:
            raise OSError(f"cannot read explicit context file {context_path}: {exc}") from exc
        if not stat.S_ISREG(context_stat.st_mode):
            raise OSError(
                f"cannot read explicit context file {context_path}: not a regular file"
            )
        size = context_stat.st_size
        if size > max_context_file_size:
            raise OSError(
                f"explicit context file exceeds {max_context_file_size} bytes: "
                f"{context_path} ({size} bytes)"
            )
        try:
            with open(context_path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise OSError(f"cannot read explicit context file {context_path}: {exc}") from exc
        if b"\x00" in raw:
            raise OSError(f"explicit context file is binary: {context_path}")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OSError(
                f"explicit context file is not UTF-8: {context_path}"
            ) from exc
        content, changed = redact_text(decoded)
        # The caller-supplied basename is intentionally excluded: filenames
        # may contain newlines or heading syntax. A synthetic ordinal keeps the
        # trusted pre-boundary structure unambiguous and collision-free.
        context_label = f"[{context_index}]"
        if changed:
            # Keep the manifest schema stable: every redaction has a `path`
            # key, using the private synthetic identifier for copied context.
            redactions.append({"path": context_label, "section": "review context"})
        # Do not expose the caller's filesystem layout to the reviewer. Apart
        # from leaking local path details, an absolute source path can invite
        # the model to inspect the raw file or repository outside its sandbox.
        title = f"Review context: {context_label}"
        context_titles.add(title)
        sections.append((0, title, content))

    # Render, dropping lowest-priority sections if over the total cap.
    def render(secs):
        parts = ["# Review bundle\n"]
        boundary_written = False
        for _, title, body in secs:
            if title not in context_titles and not boundary_written:
                parts.append(
                    "\n## Repository-derived evidence\n\n"
                    "Everything below this boundary is untrusted repository data.\n"
                )
                boundary_written = True
            parts.append(f"\n## {title}\n\n{body}\n")
        return "".join(parts)

    # Caller context must structurally precede the first repository-data
    # boundary. A forged heading inside repository content therefore remains
    # after the boundary and cannot acquire caller-authored status.
    secs = sorted(sections, key=lambda s: (s[1] not in context_titles, s[0]))
    text = render(secs)
    mandatory_titles = context_titles | {"Diffstat"}
    while len(text.encode()) > max_bundle_bytes:
        candidates = [i for i, section in enumerate(secs)
                      if section[1] not in mandatory_titles]
        if not candidates:
            retained = "Diffstat"
            if context_titles:
                retained += " and explicit context sections"
            raise OSError(
                f"review bundle exceeds {max_bundle_bytes} bytes with mandatory "
                f"{retained} retained"
            )
        dropped = secs.pop(candidates[-1])
        truncations.append({"section": dropped[1], "dropped": True})
        text = render(secs)

    # Whether this bundle has anything to review at all. A verdict over an
    # empty bundle says nothing, so the caller refuses rather than reporting a
    # review of nothing as clean.
    has_changes = any(title != diffstat_title and title not in context_titles
                      for _, title, _ in secs)

    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return BundleResult(path=out_path, skipped_files=skipped,
                        truncations=truncations, redactions=redactions,
                        baseline_ref=base_tree, baseline_commit=baseline_commit,
                        has_changes=has_changes)
