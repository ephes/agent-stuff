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
- `anomalies.tsv`: duplicate transient markers in a single frame.

Use `summary.tsv` first to find row mismatches, then inspect `anomalies.tsv`.
Any duplicate `Working...` in one frame is a failure for Pi-style loader parity
unless the reference does the same. Then inspect the corresponding frames
directly with `sed -n '<start>,<end>p'`.

## Comparison Rules

- Compare the active frames that contain the transient marker, not just the last
  frame.
- Record row indexes for the submitted prompt, `Working...`, first assistant
  output, separators, and footer/status rows.
- Treat stale/repeated transient lines as a failure even when the row summary
  looks correct. A line-based renderer can move the cursor to the right row
  while still adding real newlines or leaving old loader rows behind.
- Do not accept "the marker appears at the same row" as proof. Also require:
  one live loader row per frame, no old loader rows above or below it, no loader
  fragments inside assistant text, and a clean settled frame after completion.
- Inspect at least one active screenshot or raw frame from each phase:
  pre-stream loader, first assistant text, loader while streaming if present,
  and settled footer.
- Treat missing transient captures as insufficient evidence; re-run with more
  frames, shorter intervals, or a slower prompt/provider.
- If one product streams quickly, use a prompt likely to trigger a longer
  response or tool calls so the transient state can be sampled.
- Prefer exact tmux text evidence before screenshots. Screenshots rendered from
  ANSI are useful for review, but HTML/ANSI replay can introduce artifacts.
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

Plain and ANSI evidence derive from one ANSI capture, with physical LF rows.

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
Boolean cells use True/False text. The Claude sampler exports summary,
frame-metrics, anomalies and the run receipt; it has no cursor/delta exports.
