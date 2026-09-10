"""CLI entry: assemble bundle, run one Pi review under a slot lock, emit result."""
import argparse
import os
import shlex
import subprocess
import sys
import time

from . import bundle as bundle_mod
from . import ledger as ledger_mod
from . import model as model_mod
from .lock import LockHeld, LockPool, write_meta
from .result import ReviewResult
from .runner import run_review
from .states import CLEAN, ISSUES, FAILED, CRASHED, INVALID

REVIEW_INSTRUCTION = """\
You are a code reviewer. Review ONLY the changes in the provided review bundle \
(diffs and any included file contents) for issues that affect correctness or \
stated requirements. You cannot edit files; respond with findings only. Do not \
flag pure style nits unless they affect correctness.

End your reply with EXACTLY one verdict block on its own lines. If there are no \
blocking issues:
REVIEW: CLEAN
Otherwise:
REVIEW: ISSUES
1. [Critical] path/to/file: what is wrong and why
2. [Warning] path/to/file: ...
Use only the severities Critical, Warning, or Suggestion. The reviewer harness \
parses the final line matching '^REVIEW: (CLEAN|ISSUES)$' as the verdict, so it \
must appear verbatim and last."""

DELTA_INSTRUCTION = """\
This is a re-review. The bundle holds only what changed since the previous \
review of this slice, not the whole change. Verify that the findings from that \
review are actually fixed and that these changes introduce no regression. \
Report every Critical you can see; keep lower severities to this delta, since \
code outside it was already reviewed and is a follow-up rather than a finding \
for this round."""

EXIT_BY_STATE = {CLEAN: 0, ISSUES: 1}  # everything in FAILED -> 2
# 3 -> no free review slot; 4 -> the slice ledger says the loop is not
# converging, so stop and hand the residual risk to the user.


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be an integer")
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _default_max_concurrent():
    try:
        return _positive_int(os.environ.get("PI_REVIEW_MAX_CONCURRENT", "3"))
    except argparse.ArgumentTypeError:
        return 3


def _build_parser():
    p = argparse.ArgumentParser(prog="pi-review-loop",
                                description="Run one Pi review over a git diff.")
    p.add_argument("--repo", default=".")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--lock-dir",
                   default=os.path.expanduser("~/.cache/pi-review-loop/locks"))
    p.add_argument("--max-concurrent", type=_positive_int,
                   default=_default_max_concurrent(),
                   help="maximum concurrent Pi review slots for this user")
    p.add_argument(
        "--model", default=None,
        help="review model (only openai-codex/gpt-5.6-sol is permitted)",
    )
    p.add_argument("--stall-timeout", type=float, default=180)
    p.add_argument("--retry-grace", type=float, default=30)
    p.add_argument("--review-deadline", type=float, default=1500)
    p.add_argument("--max-file-size", type=int, default=262144)
    p.add_argument("--max-diff-bytes-per-file", type=int, default=262144)
    p.add_argument("--max-bundle-bytes", type=int, default=2097152)
    p.add_argument("--staged-only", action="store_true")
    p.add_argument(
        "--baseline-ref",
        help="review only what changed since this baseline (a commit-ish, "
             "normally the previous round's baseline_commit). Scopes a "
             "re-review to the repair delta instead of the whole slice.")
    p.add_argument(
        "--record-baseline", action="store_true",
        help="snapshot the reviewed content as a dangling commit and report it "
             "as baseline_commit, so the next round can pass it to "
             "--baseline-ref. Writes objects to the repository; no ref is "
             "created and the caller's index and worktree are untouched.")
    p.add_argument(
        "--slice-id",
        help="record this round in the slice's cross-round ledger and report "
             "whether the loop is still converging. Use the same id for every "
             "round of one implementation slice, whichever harness runs it.")
    p.add_argument(
        "--ledger-dir",
        default=os.path.expanduser("~/.cache/review-loop/ledger"),
        help="directory holding per-slice round ledgers, shared with "
             "claude-review-loop")
    return p


def _pi_cmd(model, bundle_path, delta=False):
    # Test seam: PI_REVIEW_FAKE_CMD replaces the `pi ...` argv entirely.
    fake = os.environ.get("PI_REVIEW_FAKE_CMD")
    if fake:
        return shlex.split(fake)
    # Pi reads the bundle file directly, so the delta framing goes in the system
    # prompt rather than into the bundle: the artifact stays the exact review
    # surface.
    instruction = REVIEW_INSTRUCTION
    if delta:
        instruction = REVIEW_INSTRUCTION + "\n\n" + DELTA_INSTRUCTION
    return [
        "pi", "--mode", "json", "--no-session", "--no-tools",
        "--no-extensions", "--no-skills", "--no-prompt-templates",
        "--no-context-files", "--append-system-prompt", instruction,
        "--model", model, "--thinking", "high", f"@{bundle_path}",
    ]


def main(argv=None):
    args = _build_parser().parse_args(argv)
    os.makedirs(args.run_dir, exist_ok=True)
    existing = [name for name in os.listdir(args.run_dir)]
    if existing:
        # The run directory is harness-owned scratch: the bundler writes a
        # private index into it, and reusing a directory that already holds
        # files would both leak them into the review and risk destroying them.
        print("pi-review-loop: run directory must be new or empty",
              file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(args.lock_dir) or ".", exist_ok=True)

    model = args.model or "unresolved"
    bundle_path = os.path.join(args.run_dir, "review-bundle.md")
    try:
        b = bundle_mod.build_bundle(
            args.repo, bundle_path,
            max_file_size=args.max_file_size,
            max_diff_bytes_per_file=args.max_diff_bytes_per_file,
            max_bundle_bytes=args.max_bundle_bytes,
            staged_only=args.staged_only,
            baseline_ref=args.baseline_ref,
            record_baseline=args.record_baseline,
        )
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        err = getattr(e, "stderr", None)
        if err is None:
            err = str(e)
        elif not isinstance(err, str):
            err = (err or b"").decode(errors="replace")
        msg = f"cannot build review bundle: {(err or '').strip()}"
        print(f"pi-review-loop: {msg}", file=sys.stderr)
        now = time.monotonic()
        try:
            ReviewResult(state=CRASHED, items=[], model=model, cost=None,
                         started_at=now, ended_at=now, error=msg).write(
                             os.path.join(args.run_dir, "result.json"))
        except OSError:
            pass
        return 2

    if not b.has_changes:
        msg = "no changes to review; refusing to treat an empty bundle as clean"
        print(f"pi-review-loop: {msg}", file=sys.stderr)
        now = time.monotonic()
        ReviewResult(state=INVALID, items=[], model=model, cost=None,
                     started_at=now, ended_at=now, error=msg).write(
                         os.path.join(args.run_dir, "result.json"))
        return 2

    try:
        if os.environ.get("PI_REVIEW_FAKE_CMD"):
            model = args.model or "fake/model"
        elif args.model:
            model = model_mod.ensure_model_available(args.model)
        else:
            model = model_mod.resolve_from_cli(require_available=True)
    except model_mod.PiUnavailable as e:
        msg = f"pi unavailable: {e}"
        print(f"pi-review-loop: {msg}", file=sys.stderr)
        now = time.monotonic()
        ReviewResult(state=CRASHED, items=[], model=model, cost=None,
                     started_at=now, ended_at=now, error=msg).write(
                         os.path.join(args.run_dir, "result.json"))
        return 2
    meta = {"harness_pid": os.getpid(), "cwd": os.path.abspath(args.repo),
            "command": "pi-review-loop", "model": model, "run_dir": args.run_dir}
    try:
        with LockPool(args.lock_dir, meta, args.max_concurrent) as held_lock:
            def _record_pgid(pgid):
                write_meta(held_lock.lock_dir, {
                    **meta, "pi_pgid": pgid,
                    "lock_slot": held_lock.slot,
                    "max_concurrent": args.max_concurrent,
                })
            result = run_review(
                cmd=_pi_cmd(model, bundle_path, delta=bool(args.baseline_ref)),
                run_dir=args.run_dir,
                model=model, stall_timeout=args.stall_timeout,
                retry_grace=args.retry_grace, global_deadline=args.review_deadline,
                on_spawn=_record_pgid,
            )
    except LockHeld as e:
        print(f"pi-review-loop: {e}", file=sys.stderr)
        return 3

    # Fold bundle scope into the result and re-write result.json.
    result.skipped_files = b.skipped_files
    result.truncations = b.truncations
    result.redactions = b.redactions
    result.baseline_ref = b.baseline_ref
    # A failed round reviewed nothing, so its snapshot must not become the next
    # round's baseline: that would scope the next review against content no
    # reviewer ever saw.
    result.baseline_commit = (
        None if result.state in FAILED else b.baseline_commit)

    convergence = None
    if args.slice_id and result.state not in FAILED:
        ledger_path = ledger_mod.path_for(args.ledger_dir, args.slice_id)
        record = ledger_mod.record_for(
            result=result, model=model, effort="high", run_dir=args.run_dir,
            baseline_ref=result.baseline_ref,
            baseline_commit=result.baseline_commit,
        )
        try:
            # One lock across the append and the read: a concurrent review of
            # the same slice must not renumber this round or lend it its status.
            rounds = ledger_mod.append_and_read(ledger_path, record)
        except OSError as exc:
            # The ledger informs the stop decision; it must never withhold a
            # review that already happened.
            print(f"pi-review-loop: cannot record slice round: {exc}",
                  file=sys.stderr)
            rounds = []
        if rounds:
            status, reason = ledger_mod.assess(rounds)
            convergence = {"status": status, "reason": reason,
                           "round": len(rounds), "ledger": ledger_path}
            result.slice_id = args.slice_id
            result.round = len(rounds)
            result.convergence = convergence

    result.write(os.path.join(args.run_dir, "result.json"))

    scope = " (scoped)" if result.scoped_clean else ""
    print(f"REVIEW: {result.state}{scope}  items={len(result.items)}  "
          f"model={model}  result={os.path.join(args.run_dir, 'result.json')}")
    if result.baseline_commit:
        print(f"  baseline={result.baseline_commit}"
              "  (pass to --baseline-ref for the next round)")
    for it in result.items:
        print(f"  - [{it['severity']}] {it['path']}: {it['message']}")
    if convergence:
        print(f"  LOOP: {convergence['status']} (round {convergence['round']})"
              f" - {convergence['reason']}")
    if result.error and result.state in FAILED:
        print(f"  error: {result.error.splitlines()[-1]}", file=sys.stderr)
    if convergence and convergence["status"] == ledger_mod.ESCALATE:
        return 4
    return EXIT_BY_STATE.get(result.state, 2)
