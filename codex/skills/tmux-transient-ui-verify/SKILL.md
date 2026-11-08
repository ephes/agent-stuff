---
name: tmux-transient-ui-verify
description: Verify transient terminal UI behavior with sampled tmux frames. Use when Codex needs to compare CLI/TUI visual states that appear only while output is being generated, such as spinners, loaders, streaming assistant text, cursor/input redraws, footer placement, or pi-vs-pipy terminal chrome parity; especially when final screenshots or final logs may hide timing-dependent layout differences.
---

# Tmux Transient UI Verify

Use this skill when the behavior under review is temporary. A final screenshot
does not prove where a spinner, streaming output, cursor, or footer appeared
during generation.

## Workflow

1. Launch each CLI in its own fixed-size tmux session or pane.
   - Use the same cwd, terminal size, provider/model, env, and prompt.
   - For visual parity, unset variables such as `NO_COLOR` unless the no-color
     path is the behavior under test.
2. Capture startup state once before sending input.
3. Send the same input to every target.
4. Immediately sample frames every 50-150 ms while the UI is active.
5. Compare row positions for the relevant transient and stable markers.
6. Check frame integrity: transient UI should not leave repeated stale lines,
   interleave into assistant text, or accumulate in scrollback.
7. Keep raw `.ansi`, plain `.log`, summaries, anomaly reports, and selected
   active-frame screenshots near the audit result.
8. Do not claim visual parity from row summaries or final screenshots alone.

## Sampler

Use `scripts/sample_tmux_frames.py` to capture both ANSI and plain frames and
write a row-position summary.

Example:

```sh
python3 /path/to/tmux-transient-ui-verify/scripts/sample_tmux_frames.py \
  --out docs/audit/YYYY-MM-DD/working-placement \
  --target pipy=pipy-working \
  --target pi=pi-working \
  --send pipy='hello world!' \
  --send pi='hello world!' \
  --needle 'hello world!' \
  --needle 'Working...' \
  --needle 'Hello' \
  --transient 'Working...' \
  --frames 40 \
  --interval 0.1
```

The script writes:

- `run.json`: `state`, `frames_requested`, `frames_completed`,
  `samples_completed`, `errors`, `anomalies`.
- `frames/<label>-NN.log`: plain captured frame;
- `frames/<label>-NN.ansi`: ANSI-preserved captured frame;
- `summary.tsv`: every frame/needle row hit;
- `summary.json`: machine-readable summary;
- `frame-metrics.tsv`: per-frame counts for each marker;
- `cursor-metrics.tsv`: per-frame tmux live cursor coordinates and active-pane
  state;
- `row-deltas.tsv`: first-target-versus-other-target row deltas for every
  tracked needle plus live cursor row;
- `anomalies.tsv`: duplicate transient markers, missing markers, and row
  deltas whose absolute value exceeds `--max-row-delta` (default `0`).

Use `summary.tsv` first to find row mismatches, then inspect `anomalies.tsv`.
Any duplicate `Working...`, missing stable marker, or nonzero row delta in one
frame is a failure for Pi-style loader parity unless the reference does the
same or a wider `--max-row-delta` tolerance was intentionally set. Then inspect
the corresponding frames directly with `sed -n '<start>,<end>p'`.

## Comparison Rules

- Compare the active frames that contain the transient marker, not just the last
  frame.
- Record row indexes for the submitted prompt, `Working...`, first assistant
  output, separators, and footer/status rows.
- Inspect `row-deltas.tsv` for the submitted prompt, input separators, footer,
  and live cursor rows. The sampler now also writes row-delta failures into
  `anomalies.tsv`; if an older artifact predates that behavior, a zero anomaly
  count is not enough when stable markers are vertically displaced between
  products.
- Record the live cursor row from `cursor-metrics.tsv`, especially for the
  active pane. `capture-pane` and ANSI screenshots can show a drawn
  reverse-video cursor cell while missing the terminal's actual blinking
  cursor position.
- Treat stale/repeated transient lines as a failure even when the row summary
  looks correct. A line-based renderer can move the cursor to the right row
  while still adding real newlines or leaving old loader rows behind.
- Do not accept "the marker appears at the same row" as proof. Also require:
  one live loader row per frame, no old loader rows above or below it, no loader
  fragments inside assistant text, and a clean settled frame after completion.
- For product parity, do not rely only on selected markers. Inspect the final
  raw frame or use the project-specific terminal-screen comparator when
  available; selected marker checks can miss answer wording, retained startup
  chrome, background colors, or other visible rows that were not named as
  needles.
- Inspect at least one active screenshot or raw frame from each phase:
  pre-stream loader, first assistant text, loader while streaming if present,
  and settled footer.
- Treat missing transient captures as insufficient evidence; re-run with more
  frames, shorter intervals, or a slower prompt/provider.
- If one product streams quickly, use a prompt likely to trigger a longer
  response or tool calls so the transient state can be sampled.
- Prefer exact tmux text evidence before screenshots. Screenshots rendered from
  ANSI are useful for review, but HTML/ANSI replay can introduce artifacts.
- Do not accept a cursor screenshot alone. Compare the drawn cursor/input row
  in the frame with `#{cursor_x}` and `#{cursor_y}` from tmux; mismatches can
  produce a second blinking cursor only when the pane is active.
- If the implementation is line-oriented while the reference is a full TUI,
  be skeptical of escape-sequence fixes. Exact live loader behavior may require
  a real status region/layout layer. If repeated transient rows appear, stop and
  fix the rendering architecture or relax the parity target; do not keep
  chasing row numbers only.

## Reporting

State clearly:

- commands used to launch sessions;
- prompt sent;
- sampling interval and frame count;
- frame numbers proving the match or mismatch;
- whether `anomalies.tsv` is empty;
- which active raw frames or screenshots were inspected manually;
- known product-specific differences that are acceptable;
- limitations, such as provider-generated answer wording or missed frames.

Sampler labels must match the entire safe label pattern and be unique within
--target and --send. Intervals must be finite and nonnegative; Codex row tolerance
must also be nonnegative. Invalid configuration fails before sends or files.
Explicit --needle comparison markers must appear at least once in the reference
(or sole pane) during the run; absence throughout the capture fails even when
both panes lack them. Markers may appear partway through. Markers also listed
as --transient (including the default Working...) are optional during idle
frames, including an entirely idle run. Capture-wide missing-marker anomalies
use frame="all" in both JSON and TSV.
Per-frame one-sided marker absence still detects parity mismatches. Zero targets
is a configuration error.

Plain text and ANSI evidence derive from one ANSI capture, preserving physical
rows (no capture-pane -J joining). Comparisons use viewport rows: captured marker
rows are shifted by pane height minus captured line count, excluding history
hits outside the viewport. Raw capture metrics retain captured row indices.
Cursor metadata records pane height/history size and capture origin. Missing
cursor coordinates are null and are not treated as row -1 displacements.
Capture and cursor sampling have separate monotonic timestamps and cursor_atomic
is false: redraw/resize can occur between tmux commands, so this is an inferred
coordinate basis, not an atomic terminal snapshot.

Unavailable pane height produces coordinate_basis_unavailable, not a false
missing-marker diagnosis. Unknown visible presence is null in frame metrics;
raw counts remain available. Use cursor-metrics.json for detailed sampling
metadata and missing values. Physical rows split only at LF; Unicode line
separator characters within a terminal row do not shift coordinates.

Needles must fit within one physical pane row; text crossing a soft-wrap boundary
does not match a single needle. Use shorter markers or a wider pane.

Every tmux command has a 10-second deadline. Send/capture failures preserve
collected evidence with run.json state INCOMPLETE and exit 3; prompt sends are
never retried automatically. A complete capture has state COMPLETE, exiting 0
when checks pass or 1 for anomalies. Output must be absent or an empty real
directory; populated destinations are refused before sends, preserving prior
captures. Interrupted runs retain an INCOMPLETE receipt. Use a fresh
output directory for each rerun. All exports use explicit UTF-8; TSV uses the
standard quoted excel-tab dialect, preserving tabs/newlines/quotes in values.
JSON null is an empty TSV cell; other scalar values use their text form.

Exit codes distinguish configuration/refusal (2, no new receipt) from started-run
capture/publication failure (3, INCOMPLETE receipt when writable). A refusal never
makes a prior receipt current. COMPLETE runs exit 0 when clean or 1 for anomalies.
TSV columns include all JSON metadata; parse headers rather than fixed offsets.
Boolean cells use True/False text; cursor pane_active retains its legacy 0/1.
