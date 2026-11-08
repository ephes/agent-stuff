#!/usr/bin/env python3
"""Sample tmux panes and summarize transient terminal UI integrity."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
import re
import subprocess
import time
from pathlib import Path


TMUX_TIMEOUT = 10

LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_label_value(raw: str, *, option: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"{option} must be LABEL=VALUE")
    label, value = raw.split("=", 1)
    if not label or not LABEL_RE.fullmatch(label):
        raise argparse.ArgumentTypeError(
            f"{option} label must match {LABEL_RE.pattern}"
        )
    if not value:
        raise argparse.ArgumentTypeError(f"{option} value must not be empty")
    return label, value


def run_tmux(args: list[str]) -> bytes:
    return subprocess.check_output(["tmux", *args], timeout=TMUX_TIMEOUT)


def capture(target: str, *, ansi: bool, history_start: str) -> str:
    args = ["capture-pane", "-t", target, "-p", "-S", history_start]
    if ansi:
        args.insert(3, "-e")
    return run_tmux(args).decode("utf-8", errors="replace")


ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


def send_prompt(target: str, prompt: str) -> None:
    subprocess.check_call(["tmux", "send-keys", "-t", target, "-l", prompt], timeout=TMUX_TIMEOUT)
    subprocess.check_call(["tmux", "send-keys", "-t", target, "Enter"], timeout=TMUX_TIMEOUT)


def pane_lines(text):
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def row_hits(text: str, needles: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row_index, line in enumerate(pane_lines(text)):
        for needle in needles:
            if needle in line:
                rows.append(
                    {
                        "needle": needle,
                        "row": row_index,
                        "line": line.rstrip(),
                    }
                )
    return rows


def frame_metrics(
    *,
    label: str,
    frame_index: int,
    text: str,
    needles: list[str],
    transient_needles: list[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    lines = pane_lines(text)
    metrics: list[dict[str, object]] = []
    anomalies: list[dict[str, object]] = []
    for needle in needles:
        rows = [idx for idx, line in enumerate(lines) if needle in line]
        metrics.append(
            {
                "label": label,
                "frame": frame_index,
                "needle": needle,
                "count": len(rows),
                "rows": ",".join(str(row) for row in rows),
            }
        )
    for needle in transient_needles:
        rows = [idx for idx, line in enumerate(lines) if needle in line]
        if len(rows) > 1:
            anomalies.append(
                {
                    "label": label,
                    "frame": frame_index,
                    "kind": "duplicate_transient",
                    "needle": needle,
                    "count": len(rows),
                    "rows": ",".join(str(row) for row in rows),
                    "detail": "transient marker appears more than once in one frame",
                }
            )
    return metrics, anomalies


def write_receipt(path: Path, receipt: dict) -> None:
    payload = json.dumps(receipt, indent=2, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".run-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = None
            fh.write(payload)
        os.replace(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sample tmux panes and summarize transient UI markers."
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        type=lambda raw: parse_label_value(raw, option="--target"),
        help="LABEL=TMUX_TARGET. Repeat for each pane/session.",
    )
    parser.add_argument(
        "--send",
        action="append",
        default=[],
        type=lambda raw: parse_label_value(raw, option="--send"),
        help="LABEL=PROMPT. Sends literal prompt plus Enter before sampling.",
    )
    parser.add_argument("--needle", action="append")
    parser.add_argument(
        "--transient",
        action="append",
        help=(
            "Marker that should appear at most once per frame. Defaults to "
            "Working... when omitted."
        ),
    )
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--history-start", default="-500")
    args = parser.parse_args()

    if not args.target:
        parser.error("at least one --target LABEL=TMUX_TARGET is required")
    if args.frames < 1:
        parser.error("--frames must be >= 1")
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error("--interval must be finite and >= 0")

    if len({label for label, _ in args.target}) != len(args.target):
        parser.error("duplicate --target labels")
    if len({label for label, _ in args.send}) != len(args.send):
        parser.error("duplicate --send labels")
    transient_needles = args.transient if args.transient else ["Working..."]
    needles = list(args.needle) if args.needle else list(transient_needles)
    for needle in transient_needles:
        if needle not in needles:
            needles.append(needle)
    targets = dict(args.target)
    sends = dict(args.send)
    unknown_send_labels = sorted(set(sends) - set(targets))
    if unknown_send_labels:
        parser.error(f"--send label has no matching --target: {unknown_send_labels}")

    frames_dir = args.out / "frames"
    try:
        if args.out.is_symlink() or (args.out.exists() and any(args.out.iterdir())):
            parser.error("--out must be absent or an empty real directory")
        args.out.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir()  # exclusive run ownership, before any prompt
    except OSError as exc:
        parser.error(f"cannot prepare --out: {type(exc).__name__}")

    receipt = {"state": "INCOMPLETE", "frames_requested": args.frames,
               "frames_completed": 0, "samples_completed": 0, "errors": [], "anomalies": 0}
    summary, metrics, anomalies = [], [], []
    try:
        write_receipt(args.out / "run.json", receipt)
    except OSError as exc:
        print(f"cannot initialize capture receipt: {type(exc).__name__}")
        return 3
    phase = "send"
    try:
        for label, prompt in sends.items():
            phase = f"send {label}"
            send_prompt(targets[label], prompt)
        for frame_index in range(args.frames):
            frame_name = f"{frame_index:02d}"
            for label, target in targets.items():
                phase = f"capture {label} frame {frame_index}"
                ansi = capture(target, ansi=True, history_start=args.history_start)
                plain = ANSI_RE.sub("", ansi)
                (frames_dir / f"{label}-{frame_name}.log").write_text(plain, encoding="utf-8")
                (frames_dir / f"{label}-{frame_name}.ansi").write_text(ansi, encoding="utf-8")

                for hit in row_hits(plain, needles):
                    summary.append({"label": label, "frame": frame_index, **hit})
                rows, found = frame_metrics(label=label, frame_index=frame_index,
                    text=plain, needles=needles, transient_needles=transient_needles)

                metrics.extend(rows)
                anomalies.extend(found)
                receipt["samples_completed"] += 1
            receipt["frames_completed"] += 1
            if frame_index != args.frames - 1:
                phase = f"interval after frame {frame_index}"
                time.sleep(args.interval)
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        receipt["errors"].append(f"{phase}: {type(exc).__name__}")

    exports = [("summary", summary, ["label", "frame", "needle", "row", "line"]),
               ("frame-metrics", metrics, ["label", "frame", "needle", "count", "rows"])]
    exports.append(("anomalies", anomalies, ["label", "frame", "kind", "needle", "count", "rows", "detail"]))
    try:
        for name, records, defaults in exports:
            (args.out / f"{name}.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            rows = records
            fields = list(dict.fromkeys(defaults + [key for item in rows for key in item]))
            with (args.out / f"{name}.tsv").open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, dialect="excel-tab", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    except OSError as exc:
        receipt["errors"].append(f"export: {type(exc).__name__}")
    if not receipt["errors"]:
        receipt["state"] = "COMPLETE"
    receipt["anomalies"] = len(anomalies)
    try:
        write_receipt(args.out / "run.json", receipt)
    except OSError as exc:
        print(f"cannot finalize capture receipt: {type(exc).__name__}")
        return 3
    print(f"wrote {args.out}")
    print(f"{receipt['state']}: {len(anomalies)} anomalies")
    return 3 if receipt["errors"] else 1 if anomalies else 0


if __name__ == "__main__":
    raise SystemExit(main())
