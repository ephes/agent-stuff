"""Copy caller-selected files into the review root as untrusted evidence.

The reviewer can read nothing outside its review root, so it cannot open the
unchanged code around a diff or the backend a change depends on. An evidence
file puts one such file in front of it - redacted with the same rules as the
bundle, refused outright under a secret-looking name, and labelled as
repository data rather than instructions. Unlike `--context-file`, which is the
caller's own trusted text, evidence is always untrusted.
"""
import os
import stat

from ._shared import redact

EVIDENCE_DIR = "evidence"


def _safe_name(index, path):
    base = os.path.basename(path) or "file"
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)
    return f"{index:02d}-{cleaned}"


def copy_evidence(paths, review_root, *, max_size):
    """Return (entries, redactions). Raises OSError/ValueError on a file that
    cannot be sent faithfully; nothing is silently omitted."""
    entries, redactions = [], []
    if not paths:
        return entries, redactions
    target_dir = os.path.join(review_root, EVIDENCE_DIR)
    os.makedirs(target_dir, mode=0o700, exist_ok=True)
    for index, path in enumerate(paths, start=1):
        if redact.is_secret_path(path):
            raise ValueError(f"evidence file has a secret-looking path: {path}")
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise OSError(f"cannot read evidence file {path}: {exc}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"cannot read evidence file {path}: not a regular file")
        if info.st_size > max_size:
            raise ValueError(
                f"evidence file exceeds {max_size} bytes: {path} ({info.st_size} bytes)")
        with open(path, "rb") as fh:
            data = fh.read()
        if b"\0" in data:
            raise ValueError(f"evidence file is binary: {path}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"evidence file is not UTF-8: {path}") from exc
        text, changed = redact.redact_text(text)
        name = _safe_name(index, path)
        with open(os.path.join(target_dir, name), "w", encoding="utf-8") as fh:
            fh.write(text)
        label = f"{EVIDENCE_DIR}/{name}"
        if changed:
            redactions.append({"path": label, "section": "evidence file"})
        entries.append({"source": os.path.abspath(path), "file": label,
                        "redacted": changed})
    return entries, redactions
