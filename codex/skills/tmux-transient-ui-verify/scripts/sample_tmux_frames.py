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
    try:
        if args.out.is_symlink() or (args.out.exists() and any(args.out.iterdir())):
            parser.error("--out must be absent or an empty real directory")
        args.out.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir()  # exclusive run ownership, before any prompt
    except OSError as exc:
        parser.error(f"cannot prepare --out: {type(exc).__name__}")

    receipt = {"state": "INCOMPLETE", "frames_requested": args.frames,
               "frames_completed": 0, "samples_completed": 0, "errors": [], "anomalies": 0}
    summary, metrics, anomalies, cursor_metrics = [], [], [], []
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
                plain, ansi, cursor = sample_frame(target, args.history_start)
                (frames_dir / f"{label}-{frame_name}.log").write_text(plain, encoding="utf-8")
                (frames_dir / f"{label}-{frame_name}.ansi").write_text(ansi, encoding="utf-8")
                cursor_metrics.append({"label": label, "frame": frame_index, **cursor})
                for hit in row_hits(plain, needles):
                    summary.append({"label": label, "frame": frame_index, **hit})
                rows, found = frame_metrics(label=label, frame_index=frame_index,
                    text=plain, needles=needles, transient_needles=transient_needles)
                if cursor.get("capture_origin") is None:
                    found.append({"label": label, "frame": frame_index,
                        "kind": "coordinate_basis_unavailable", "needle": "", "count": "", "rows": "",
                        "detail": "pane height unavailable; viewport alignment cannot be compared"})
                for metric in rows:
                    metric["visible"] = (None if cursor.get("capture_origin") is None and metric["count"]
                                         else _first_viewport_row(metric, cursor) is not None)
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
    deltas = row_delta_metrics(metrics=metrics, cursor_metrics=cursor_metrics,
                               labels=target_labels, required_needles=set())
    anomalies.extend(row_delta_anomalies(deltas, max_row_delta=args.max_row_delta))
    if not receipt["errors"]:
        anomalies.extend(required_marker_anomalies(metrics, target_labels, required_needles))
    exports.extend([("cursor-metrics", cursor_metrics, ["label", "frame", "cursor_x", "cursor_y", "pane_active"]),
                    ("row-deltas", deltas, ["frame", "kind", "name", "reference_label", "reference_row", "target_label", "target_row", "delta"])])
    exports.append(("anomalies", anomalies, ["label", "frame", "kind", "needle", "count", "rows", "detail"]))
    try:
        for name, records, defaults in exports:
            (args.out / f"{name}.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            rows = records
            if name == "cursor-metrics":
                rows = [dict(item, pane_active=int(item["pane_active"])) for item in records]
            if name == "row-deltas":
                rows = [{**{k: v for k, v in item.items() if k != "label"},
                         "target_label": item["label"]} for item in records]
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
