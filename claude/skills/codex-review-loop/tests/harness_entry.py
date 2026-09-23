#!/usr/bin/env python3
"""Test-only entry point: runs the production CLI with the fake reviewer.

The installed `bin/codex-review-loop` reads no variable that can replace the
reviewer. Only this script, which lives with the tests, passes the fake's
executable and its controls to `main()`.
"""
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codex_review_loop.cli import main  # noqa: E402

if __name__ == "__main__":
    extra = {k: v for k, v in os.environ.items() if k.startswith("FAKE_CODEX_")}
    raise SystemExit(main(codex_bin=shlex.split(os.environ["CODEX_REVIEW_TEST_BIN"]),
                          extra_env=extra))
