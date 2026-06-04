#!/usr/bin/env python3
"""Sample tmux panes and summarize transient terminal UI integrity."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path


LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_label_value(raw: str, *, option: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"{option} must be LABEL=VALUE")
    label, value = raw.split("=", 1)
    if not label or not LABEL_RE.match(label):
        raise argparse.ArgumentTypeError(
            f"{option} label must match {LABEL_RE.pattern}"
        )
    if not value:
        raise argparse.ArgumentTypeError(f"{option} value must not be empty")
    return label, value


def run_tmux(args: list[str]) -> bytes:
    return subprocess.check_output(["tmux", *args])


def capture(target: str, *, ansi: bool, history_start: str) -> str:
    args = ["capture-pane", "-t", target, "-p", "-J", "-S", history_start]
    if ansi:
        args.insert(3, "-e")
    return run_tmux(args).decode("utf-8", errors="replace")


def send_prompt(target: str, prompt: str) -> None:
    subprocess.check_call(["tmux", "send-keys", "-t", target, "-l", prompt])
    subprocess.check_call(["tmux", "send-keys", "-t", target, "Enter"])


def row_hits(text: str, needles: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row_index, line in enumerate(text.splitlines()):
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
    lines = text.splitlines()
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
    if args.interval < 0:
        parser.error("--interval must be >= 0")

    transient_needles = args.transient if args.transient else ["Working..."]
    needles = args.needle if args.needle else list(transient_needles)
    for needle in transient_needles:
        if needle not in needles:
            needles.append(needle)
    targets = dict(args.target)
    sends = dict(args.send)
    unknown_send_labels = sorted(set(sends) - set(targets))
    if unknown_send_labels:
        parser.error(f"--send label has no matching --target: {unknown_send_labels}")

    frames_dir = args.out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    for label, prompt in sends.items():
        send_prompt(targets[label], prompt)

    summary: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []
    anomalies: list[dict[str, object]] = []
    for frame_index in range(args.frames):
        frame_name = f"{frame_index:02d}"
        for label, target in targets.items():
            plain = capture(target, ansi=False, history_start=args.history_start)
            ansi = capture(target, ansi=True, history_start=args.history_start)
            (frames_dir / f"{label}-{frame_name}.log").write_text(plain)
            (frames_dir / f"{label}-{frame_name}.ansi").write_text(ansi)
            hits = row_hits(plain, needles)
            for hit in hits:
                summary.append({"label": label, "frame": frame_index, **hit})
            frame_metric_rows, frame_anomalies = frame_metrics(
                label=label,
                frame_index=frame_index,
                text=plain,
                needles=needles,
                transient_needles=transient_needles,
            )
            metrics.extend(frame_metric_rows)
            anomalies.extend(frame_anomalies)
        if frame_index != args.frames - 1:
            time.sleep(args.interval)

    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out / "frame-metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n"
    )
    (args.out / "anomalies.json").write_text(
        json.dumps(anomalies, indent=2) + "\n"
    )
    with (args.out / "summary.tsv").open("w", encoding="utf-8") as handle:
        handle.write("label\tframe\tneedle\trow\tline\n")
        for item in summary:
            line = str(item["line"]).replace("\t", " ").replace("\n", " ")
            handle.write(
                f"{item['label']}\t{item['frame']}\t{item['needle']}"
                f"\t{item['row']}\t{line}\n"
            )
    with (args.out / "frame-metrics.tsv").open("w", encoding="utf-8") as handle:
        handle.write("label\tframe\tneedle\tcount\trows\n")
        for item in metrics:
            handle.write(
                f"{item['label']}\t{item['frame']}\t{item['needle']}"
                f"\t{item['count']}\t{item['rows']}\n"
            )
    with (args.out / "anomalies.tsv").open("w", encoding="utf-8") as handle:
        handle.write("label\tframe\tkind\tneedle\tcount\trows\tdetail\n")
        for item in anomalies:
            handle.write(
                f"{item['label']}\t{item['frame']}\t{item['kind']}"
                f"\t{item['needle']}\t{item['count']}\t{item['rows']}"
                f"\t{item['detail']}\n"
            )
    print(f"wrote {args.out}")
    print(f"anomalies: {len(anomalies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
