#!/usr/bin/env python3
"""Sample tmux panes and summarize transient terminal UI integrity."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from pathlib import Path


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
    return subprocess.check_output(["tmux", *args])


def capture(target: str, *, ansi: bool, history_start: str) -> str:
    args = ["capture-pane", "-t", target, "-p", "-S", history_start]
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
            "#{cursor_x}\t#{cursor_y}\t#{pane_active}\t#{pane_height}\t#{history_size}",
        ]
    ).decode("utf-8", errors="replace")
    parts = raw.rstrip("\n").split("\t")
    cursor_x = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else None
    cursor_y = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
    pane_active = parts[2] == "1" if len(parts) >= 3 else False
    return {
        "cursor_x": cursor_x,
        "cursor_y": cursor_y,
        "pane_active": pane_active,
        "pane_height": int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() and int(parts[3]) > 0 else None,
        "history_size": int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else None,
    }


ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


def sample_frame(target: str, history_start: str):
    started = time.monotonic()
    ansi = capture(target, ansi=True, history_start=history_start)
    captured = time.monotonic()
    plain = ANSI_RE.sub("", ansi)
    cursor_started = time.monotonic()
    cursor = cursor_position(target)
    cursor_finished = time.monotonic()
    height = cursor.get("pane_height")
    cursor.update(capture_started_s=started, capture_finished_s=captured,
                  cursor_started_s=cursor_started, cursor_finished_s=cursor_finished,
                  cursor_atomic=False, coordinate_basis="viewport" if height else "unavailable",
                  capture_origin=height - len(pane_lines(plain)) if height else None)
    return plain, ansi, cursor


def _first_viewport_row(item, cursor):
    origin = cursor.get("capture_origin", 0)
    if origin is None:
        return None
    height = cursor.get("pane_height")
    for raw in str(item["rows"]).split(","):
        if raw:
            row = int(raw) + origin
            if height is None or 0 <= row < height:
                return row
    return None


def send_prompt(target: str, prompt: str) -> None:
    subprocess.check_call(["tmux", "send-keys", "-t", target, "-l", prompt])
    subprocess.check_call(["tmux", "send-keys", "-t", target, "Enter"])


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


def row_delta_metrics(
    *,
    metrics: list[dict[str, object]],
    cursor_metrics: list[dict[str, object]],
    labels: list[str],
    required_needles: set[str] | None = None,
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
                left_first = _first_viewport_row(left, cursor_by_key.get((reference, frame_index), {}))
                right_first = _first_viewport_row(right, cursor_by_key.get((target_label, frame_index), {}))
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
                        "required": needle in (required_needles or set()),
                        "coordinate_available": all(cursor_by_key.get((label, frame_index), {}).get("capture_origin", 0) is not None
                                                    for label in (reference, target_label)),
                        "reference_row": left_first,
                        "target_row": right_first,
                        "delta": delta,
                    }
                )
            left_cursor = cursor_by_key.get((reference, frame_index))
            right_cursor = cursor_by_key.get((target_label, frame_index))
            if left_cursor is not None and right_cursor is not None:
                left_row = left_cursor.get("cursor_y")
                right_row = right_cursor.get("cursor_y")
                left_row = left_row if isinstance(left_row, int) and left_row >= 0 else None
                right_row = right_row if isinstance(right_row, int) and right_row >= 0 else None
                rows.append(
                    {
                        "frame": frame_index,
                        "kind": "cursor",
                        "label": target_label,
                        "reference_label": reference,
                        "name": "cursor_y",
                        "reference_row": left_row,
                        "target_row": right_row,
                        "delta": right_row - left_row if left_row is not None and right_row is not None else None,
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
        if not item.get("coordinate_available", True):
            continue
        if item["kind"] == "cursor" and (reference_row is None or target_row is None):
            continue
        if reference_row is None and target_row is None and not item.get("required", False):
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


def required_marker_anomalies(metrics, labels, required_needles):
    reference = labels[0]
    return [{"label": reference, "frame": "all", "kind": "missing_marker",
             "needle": needle, "count": 0, "rows": "",
             "detail": "required marker absent from reference throughout capture"}
            for needle in sorted(required_needles)
            if not any(item["label"] == reference and item["needle"] == needle
                       and item.get("visible", item["count"] > 0) in (True, None) for item in metrics)]


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

    if args.max_row_delta < 0:
        parser.error("--max-row-delta must be >= 0")
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
    required_needles = set(args.needle or []) - set(transient_needles)
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
            plain, ansi, cursor = sample_frame(target, args.history_start)
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
            if cursor.get("capture_origin") is None:
                frame_anomalies.append({"label": label, "frame": frame_index,
                    "kind": "coordinate_basis_unavailable", "needle": "", "count": "", "rows": "",
                    "detail": "pane height unavailable; viewport alignment cannot be compared"})
            for metric in frame_metric_rows:
                metric["visible"] = (None if cursor.get("capture_origin") is None and metric["count"]
                                     else _first_viewport_row(metric, cursor) is not None)
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
        required_needles=set(),
    )
    anomalies.extend(
        row_delta_anomalies(row_deltas, max_row_delta=args.max_row_delta)
    )
    anomalies.extend(required_marker_anomalies(metrics, target_labels, required_needles))
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
