"""Cross-round record for one implementation slice.

A single review can only report what this round found. Whether the loop is
converging is a question about the rounds together: are required findings going
down, or has the same one now survived two repair attempts? The driver is
supposed to answer that, but it is exactly the state a fresh context or a
compacted session no longer has - and an agent that cannot see the previous
rounds tends to run one more.

So each completed round appends one summary-safe line here, keyed by slice, and
the harness reads them back to decide whether another round is still worth
running. Only counts, paths, and fingerprints are stored: no finding text, no
repository content.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time

CONVERGED = "converged"
PROGRESS = "progress"
ESCALATE = "escalate"

# A finding that survives this many consecutive rounds is not being fixed by
# another round of the same conversation.
REPEAT_ROUND_LIMIT = 3
# Rounds in a row that fail to reduce the required-finding count.
STALL_ROUND_LIMIT = 2

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_NOISE = re.compile(r"[^a-z]+")


def slug(slice_id):
    """Filename for a caller-chosen slice id, collision-safe for odd input."""
    cleaned = _UNSAFE.sub("-", slice_id).strip("-.")[:64]
    digest = hashlib.sha1(slice_id.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned or 'slice'}-{digest}.jsonl"


def path_for(ledger_dir, slice_id):
    return os.path.join(ledger_dir, slug(slice_id))


def fingerprint(item):
    """Identify a finding across rounds.

    Line numbers move as repairs land, so the fingerprint keeps the severity and
    path and reduces the message to its letters: the same complaint after the
    code shifted still matches.

    It does not survive a genuine rewording - a reviewer that restates the same
    objection in new words produces a new fingerprint, and the survivor rule
    misses it. The count-stall rule is the backstop for that case, which is why
    both exist.
    """
    message = _NOISE.sub(" ", (item.get("message") or "").lower()).strip()
    basis = "|".join((
        item.get("severity") or "",
        item.get("path") or "",
        message[:160],
    ))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def summarize(items):
    """Per-severity counts plus fingerprints, without any finding text."""
    counts = {"Critical": 0, "Warning": 0, "Suggestion": 0}
    findings = []
    for item in items:
        severity = item.get("severity")
        if severity in counts:
            counts[severity] += 1
        findings.append({
            "severity": severity,
            "path": item.get("path"),
            "fingerprint": fingerprint(item),
        })
    return counts, findings


def required_count(round_record):
    counts = round_record.get("counts") or {}
    return int(counts.get("Critical", 0)) + int(counts.get("Warning", 0))


def _clean_counts(record):
    """Coerce a record's counts to integers, dropping anything unusable.

    The ledger is written by this harness, but it is a plain file on disk that
    anything can corrupt. A count of `"many"` must not reach `assess` and turn a
    review that already completed into a crash.
    """
    counts = record.get("counts")
    cleaned = {}
    if isinstance(counts, dict):
        for key in ("Critical", "Warning", "Suggestion"):
            value = counts.get(key, 0)
            cleaned[key] = value if isinstance(value, int) and not isinstance(
                value, bool) else 0
    else:
        cleaned = {"Critical": 0, "Warning": 0, "Suggestion": 0}
    record["counts"] = cleaned
    findings = record.get("findings")
    record["findings"] = [f for f in findings if isinstance(f, dict)] \
        if isinstance(findings, list) else []
    return record


def read_rounds(path):
    """Every usable round for a slice, oldest first.

    A damaged, foreign, or undecodable line is skipped rather than fatal: a
    ledger is an aid to the decision, and losing it must never block or crash a
    review that already ran. Undecodable bytes are replaced rather than raised,
    so one bad byte cannot hide the rounds after it.
    """
    rounds = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    rounds.append(_clean_counts(record))
    except OSError:
        return []
    return rounds


def append_round(path, record):
    """Append one round under an exclusive lock.

    Independent reviews of the same slice may run at once, and a torn line
    would be dropped by the reader above - quietly losing the very history the
    stop rules depend on.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode("utf-8"))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def append_and_read(path, record):
    """Append this round and read the slice back under one exclusive lock.

    Reading after releasing the lock lets a concurrent review of the same slice
    append in between, which would number this round wrongly and attach the
    other run's convergence status to this result.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode("utf-8"))
        os.lseek(fd, 0, os.SEEK_SET)
        raw = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    rounds = []
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            rounds.append(_clean_counts(parsed))
    return rounds


def record_for(*, result, model, effort, run_dir, baseline_ref=None,
               baseline_commit=None, now=None):
    counts, findings = summarize(result.items)
    return {
        "at": round(now if now is not None else time.time(), 3),
        "state": result.state,
        "model": model,
        "effort": effort,
        "counts": counts,
        "findings": findings,
        "duration_s": round(result.ended_at - result.started_at, 3),
        "baseline_ref": baseline_ref,
        "baseline_commit": baseline_commit,
        "scoped": bool(result.skipped_files or result.truncations
                       or result.redactions),
        "run_dir": run_dir,
    }


def assess(rounds):
    """Decide whether another fix/re-review round is still worth running.

    Returns (status, reason). `escalate` means stop the loop and hand the
    residual risk to the user - not that the findings are resolved.
    """
    if not rounds:
        return PROGRESS, "no recorded rounds for this slice"

    latest = rounds[-1]
    required = required_count(latest)
    counts = latest.get("counts") or {}
    suggestions = int(counts.get("Suggestion", 0))
    round_no = len(rounds)

    if required == 0 and suggestions == 0:
        return CONVERGED, f"round {round_no} left no findings"

    repeated = _repeated_fingerprint(rounds)
    if repeated:
        return ESCALATE, (
            f"a {repeated['severity']} finding on {repeated['path']} has now "
            f"survived {repeated['rounds']} consecutive rounds; another round "
            "of the same conversation will not fix it"
        )

    if required == 0:
        return CONVERGED, (
            f"round {round_no} left {suggestions} Suggestion(s) and no "
            "Critical or Warning; make the proportionality decision and stop"
        )

    stalled = _stalled_rounds(rounds)
    if stalled >= STALL_ROUND_LIMIT:
        history = ", ".join(str(required_count(r)) for r in rounds[-(stalled + 1):])
        return ESCALATE, (
            f"the Critical/Warning count has not decreased across {stalled} "
            f"consecutive rounds ({history}); stop and report the residual risk"
        )

    return PROGRESS, (
        f"round {round_no} left {required} Critical/Warning finding(s); "
        "repair and re-review the delta"
    )


def _repeated_fingerprint(rounds):
    """The first required finding present in the last REPEAT_ROUND_LIMIT rounds."""
    if len(rounds) < REPEAT_ROUND_LIMIT:
        return None
    window = rounds[-REPEAT_ROUND_LIMIT:]
    seen = None
    for finding in window[-1].get("findings") or []:
        if finding.get("severity") not in ("Critical", "Warning"):
            continue
        mark = finding.get("fingerprint")
        if all(any(other.get("fingerprint") == mark
                   for other in (r.get("findings") or []))
               for r in window[:-1]):
            seen = {
                "severity": finding.get("severity"),
                "path": finding.get("path"),
                "rounds": REPEAT_ROUND_LIMIT,
            }
            break
    return seen


def _stalled_rounds(rounds):
    """How many consecutive latest rounds failed to reduce required findings."""
    stalled = 0
    for older, newer in zip(reversed(rounds[:-1]), reversed(rounds)):
        if required_count(newer) < required_count(older):
            break
        stalled += 1
    return stalled
