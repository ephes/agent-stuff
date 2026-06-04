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


def cursor_position(target: str) -> dict[str, object]:
    raw = run_tmux(
        [
            "display-message",
            "-p",
            "-t",
            target,
            "#{cursor_x}\t#{cursor_y}\t#{pane_active}",
        ]
    ).decode("utf-8", errors="replace")
    parts = raw.rstrip("\n").split("\t")
    cursor_x = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else -1
    cursor_y = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else -1
    pane_active = parts[2] == "1" if len(parts) >= 3 else False
    return {
        "cursor_x": cursor_x,
        "cursor_y": cursor_y,
        "pane_active": pane_active,
    }


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


def row_delta_metrics(
    *,
    metrics: list[dict[str, object]],
    cursor_metrics: list[dict[str, object]],
    labels: list[str],
) -> list[dict[str, object]]:
    if len(labels) < 2:
        return []
    reference = labels[0]
    metric_by_key = {
        (str(item["label"]), int(item["frame"]), str(item["needle"])): item
        for item in metrics
    }
    cursor_by_key = {
        (str(item["label"]), int(item["frame"])): item
        for item in cursor_metrics
    }
    frames = sorted({int(item["frame"]) for item in metrics})
    needles = sorted({str(item["needle"]) for item in metrics})
    rows: list[dict[str, object]] = []
    for frame_index in frames:
        for target_label in labels[1:]:
            for needle in needles:
                left = metric_by_key.get((reference, frame_index, needle))
                right = metric_by_key.get((target_label, frame_index, needle))
                if left is None or right is None:
                    continue
                left_rows = str(left["rows"])
                right_rows = str(right["rows"])
                left_first = (
                    int(left_rows.split(",", 1)[0]) if left_rows else None
                )
                right_first = (
                    int(right_rows.split(",", 1)[0]) if right_rows else None
                )
                delta = (
                    None
                    if left_first is None or right_first is None
                    else right_first - left_first
                )
                rows.append(
                    {
                        "frame": frame_index,
                        "kind": "needle",
                        "label": target_label,
                        "reference_label": reference,
                        "name": needle,
                        "reference_row": left_first,
                        "target_row": right_first,
                        "delta": delta,
                    }
                )
            left_cursor = cursor_by_key.get((reference, frame_index))
            right_cursor = cursor_by_key.get((target_label, frame_index))
            if left_cursor is not None and right_cursor is not None:
                left_row = int(left_cursor["cursor_y"])
                right_row = int(right_cursor["cursor_y"])
                rows.append(
                    {
                        "frame": frame_index,
                        "kind": "cursor",
                        "label": target_label,
                        "reference_label": reference,
                        "name": "cursor_y",
                        "reference_row": left_row,
                        "target_row": right_row,
                        "delta": right_row - left_row,
                    }
                )
    return rows


def row_delta_anomalies(
    row_deltas: list[dict[str, object]], *, max_row_delta: int
) -> list[dict[str, object]]:
    anomalies: list[dict[str, object]] = []
    for item in row_deltas:
        reference_row = item["reference_row"]
        target_row = item["target_row"]
        if reference_row is None and target_row is None:
            continue
        if reference_row is None or target_row is None:
            anomalies.append(
                {
                    "label": item["label"],
                    "frame": item["frame"],
                    "kind": "missing_marker",
                    "needle": item["name"],
                    "count": "",
                    "rows": "",
                    "detail": (
                        f"{item['reference_label']} row={reference_row}; "
                        f"{item['label']} row={target_row}"
                    ),
                }
            )
            continue
        delta = int(item["delta"])
        if abs(delta) > max_row_delta:
            anomalies.append(
                {
                    "label": item["label"],
                    "frame": item["frame"],
                    "kind": "row_delta",
                    "needle": item["name"],
                    "count": "",
                    "rows": f"{reference_row},{target_row}",
                    "detail": (
                        f"row delta {delta} exceeds tolerance {max_row_delta}"
                    ),
                }
            )
    return anomalies


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
    parser.add_argument("--max-row-delta", type=int, default=0)
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
    target_labels = [label for label, _target in args.target]
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
    cursor_metrics: list[dict[str, object]] = []
    for frame_index in range(args.frames):
        frame_name = f"{frame_index:02d}"
        for label, target in targets.items():
            plain = capture(target, ansi=False, history_start=args.history_start)
            ansi = capture(target, ansi=True, history_start=args.history_start)
            cursor = cursor_position(target)
            (frames_dir / f"{label}-{frame_name}.log").write_text(plain)
            (frames_dir / f"{label}-{frame_name}.ansi").write_text(ansi)
            cursor_metrics.append(
                {
                    "label": label,
                    "frame": frame_index,
                    **cursor,
                }
            )
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
    (args.out / "cursor-metrics.json").write_text(
        json.dumps(cursor_metrics, indent=2) + "\n"
    )
    row_deltas = row_delta_metrics(
        metrics=metrics,
        cursor_metrics=cursor_metrics,
        labels=target_labels,
    )
    anomalies.extend(
        row_delta_anomalies(row_deltas, max_row_delta=args.max_row_delta)
    )
    (args.out / "anomalies.json").write_text(
        json.dumps(anomalies, indent=2) + "\n"
    )
    (args.out / "row-deltas.json").write_text(
        json.dumps(row_deltas, indent=2) + "\n"
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
    with (args.out / "cursor-metrics.tsv").open("w", encoding="utf-8") as handle:
        handle.write("label\tframe\tcursor_x\tcursor_y\tpane_active\n")
        for item in cursor_metrics:
            handle.write(
                f"{item['label']}\t{item['frame']}\t{item['cursor_x']}"
                f"\t{item['cursor_y']}\t{int(bool(item['pane_active']))}\n"
            )
    with (args.out / "row-deltas.tsv").open("w", encoding="utf-8") as handle:
        handle.write(
            "frame\tkind\tname\treference_label\treference_row"
            "\ttarget_label\ttarget_row\tdelta\n"
        )
        for item in row_deltas:
            reference_row = (
                "" if item["reference_row"] is None else str(item["reference_row"])
            )
            target_row = "" if item["target_row"] is None else str(item["target_row"])
            delta = "" if item["delta"] is None else str(item["delta"])
            handle.write(
                f"{item['frame']}\t{item['kind']}\t{item['name']}"
                f"\t{item['reference_label']}\t{reference_row}"
                f"\t{item['label']}\t{target_row}\t{delta}\n"
            )
    print(f"wrote {args.out}")
    print(f"anomalies: {len(anomalies)}")
    return 1 if anomalies else 0


if __name__ == "__main__":
    raise SystemExit(main())
