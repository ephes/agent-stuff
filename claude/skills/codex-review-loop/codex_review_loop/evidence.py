"""Copy caller-selected files into the review root as untrusted evidence.

The reviewer can read its copy of the repository under review, but nothing
outside it - not the backend a client change mirrors, not another project. An
evidence file puts one such file in front of it - redacted with the same rules as the
bundle, refused outright under a secret-looking name, and labelled as
repository data rather than instructions. Unlike `--context-file`, which is the
caller's own trusted text, evidence is always untrusted.
"""
import os

from ._shared import bundle, redact

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
        data = bundle.read_regular_file(path, max_size)
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
