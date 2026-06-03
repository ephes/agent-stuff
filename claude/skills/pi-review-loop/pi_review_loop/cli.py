"""CLI entry: assemble bundle, run one Pi review under the lock, emit result."""
import argparse
import os
import shlex
import sys

from . import bundle as bundle_mod
from . import model as model_mod
from .lock import Lock, LockHeld
from .runner import run_review
from .states import CLEAN, ISSUES, FAILED

EXIT_BY_STATE = {CLEAN: 0, ISSUES: 1}  # everything in FAILED -> 2


def _build_parser():
    p = argparse.ArgumentParser(prog="pi-review-loop",
                                description="Run one Pi review over a git diff.")
    p.add_argument("--repo", default=".")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--lock-dir",
                   default=os.path.expanduser("~/.cache/pi-review-loop/lock"))
    p.add_argument("--model", default=None, help="override model id")
    p.add_argument("--stall-timeout", type=float, default=180)
    p.add_argument("--retry-grace", type=float, default=30)
    p.add_argument("--review-deadline", type=float, default=1500)
    p.add_argument("--max-file-size", type=int, default=262144)
    p.add_argument("--max-diff-bytes-per-file", type=int, default=262144)
    p.add_argument("--max-bundle-bytes", type=int, default=2097152)
    p.add_argument("--staged-only", action="store_true")
    return p


def _pi_cmd(model, bundle_path):
    # Test seam: PI_REVIEW_FAKE_CMD replaces the `pi ...` argv entirely.
    fake = os.environ.get("PI_REVIEW_FAKE_CMD")
    if fake:
        return shlex.split(fake)
    return [
        "pi", "--mode", "json", "--no-session", "--no-tools",
        "--no-extensions", "--no-skills", "--no-prompt-templates",
        "--no-context-files", "--model", model, f"@{bundle_path}",
    ]


def main(argv=None):
    args = _build_parser().parse_args(argv)
    os.makedirs(args.run_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.lock_dir) or ".", exist_ok=True)

    model = args.model or model_mod.resolve_from_cli()
    bundle_path = os.path.join(args.run_dir, "review-bundle.md")
    b = bundle_mod.build_bundle(
        args.repo, bundle_path,
        max_file_size=args.max_file_size,
        max_diff_bytes_per_file=args.max_diff_bytes_per_file,
        max_bundle_bytes=args.max_bundle_bytes,
        staged_only=args.staged_only,
    )

    meta = {"harness_pid": os.getpid(), "cwd": os.path.abspath(args.repo),
            "command": "pi-review-loop", "model": model, "run_dir": args.run_dir}
    try:
        with Lock(args.lock_dir, meta):
            result = run_review(
                cmd=_pi_cmd(model, bundle_path), run_dir=args.run_dir,
                model=model, stall_timeout=args.stall_timeout,
                retry_grace=args.retry_grace, global_deadline=args.review_deadline,
            )
    except LockHeld as e:
        print(f"pi-review-loop: {e}", file=sys.stderr)
        return 3

    # Fold bundle scope into the result and re-write result.json.
    result.skipped_files = b.skipped_files
    result.truncations = b.truncations
    result.write(os.path.join(args.run_dir, "result.json"))

    scope = " (scoped)" if result.scoped_clean else ""
    print(f"REVIEW: {result.state}{scope}  items={len(result.items)}  "
          f"model={model}  result={os.path.join(args.run_dir, 'result.json')}")
    for it in result.items:
        print(f"  - [{it['severity']}] {it['path']}: {it['message']}")
    if result.error and result.state in FAILED:
        print(f"  error: {result.error.splitlines()[-1] if result.error else ''}",
              file=sys.stderr)
    return EXIT_BY_STATE.get(result.state, 2)
