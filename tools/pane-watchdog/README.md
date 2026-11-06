# pane-watchdog

Read-only scan of herdr panes for agents that wait without anyone noticing.
Python 3 stdlib only.

herdr shows a pane as `idle` whether the agent is done or stuck on a dialog.
On 2026-11-05 a worker pane hung behind an open `/usage` dialog for almost two
hours, a subagent waited on a permission prompt, and a worker waited hours for
an owner answer. Several panes also showed dim prompt suggestions ("ghost
text") in the input line, some destructive. `pane read` without
`--format ansi` drops the dim attribute, so the suggestion looks like owner
input, and a coordinator once sent Enter into three such panes.

```sh
tools/pane-watchdog/bin/pane-watchdog                    # this machine
tools/pane-watchdog/bin/pane-watchdog local claascraft   # this machine and a saved herdr machine
tools/pane-watchdog/bin/pane-watchdog studio --json
```

For each machine (`local`, or a label/id from `herdr machine list`) it runs
`herdr [--machine M] pane list`, then
`herdr [--machine M] pane read <pane> --format ansi --lines 80` for every pane
that runs an agent (panes whose `agent` field in `pane list` is empty are plain
shells and are skipped, so a shell printing these phrases is not reported).
Those are the only herdr commands it runs (enforced in code); it never sends
keys or text.

| Kind | Detected when |
|------|---------------|
| `usage-dialog` | the `/usage` settings dialog is open ("Current week (all models)", or the Settings/Status/Config/Usage tabs) |
| `trust-dialog` | the folder trust question is open |
| `permission-prompt` | a "Do you want to …?" question is open, or an "Esc to cancel" footer without another known dialog |
| `owner-question` | the turn has finished (herdr status is not `working`) and one of the last 8 lines of the last `⏺` message ends with `?` or asks ("Shall I", "Should I", "Want me to", "Soll ich", "Möchtest du", …) |
| `input-text` | the `❯` input line holds non-dim text: typed but not sent |

Dim text (SGR 2, `ESC[2m`) in the input line is a suggestion and is ignored.
The input line is the last `❯` line directly below a horizontal rule, and it
only counts when at most six status lines (no rule, message or prompt) follow
its closing rule, so a box left in scrollback does not hide a dialog below it.
While it is shown, Claude Code has no dialog open, so dialog patterns are only checked
when there is no input box (in the last 30 non-blank lines). Phrases in the
transcript above the input box therefore do not count. A question is only
looked for in the last `⏺` message within the read (no `⏺`, no
`owner-question`). Recap (`※`) and duration (`✻`) lines after it are skipped, and
"Interrupted · What should Claude do instead?" is not a question.

Output: one tab-separated line per finding on stdout,
`machine<TAB>pane<TAB>kind<TAB>snippet` (snippet at most 120 characters,
whitespace collapsed). Local panes are labelled with the short hostname
(`--local-name` overrides). `--json` prints a list of
`{machine, pane, kind, snippet}`. Scan errors (machine unreachable, pane read
failed) go to stderr as `machine<TAB>pane<TAB>error<TAB>message`.

| Exit | Meaning |
|------|---------|
| 0 | no findings |
| 1 | findings |
| 2 | at least one machine or pane could not be read (findings from the rest are still printed) |

| Variable | Effect |
|----------|--------|
| `PANE_WATCHDOG_HERDR` | `herdr` executable (default `herdr` on PATH) |

Limits: the patterns match Claude Code's terminal UI (checked against Claude
Code 2.1.318); other agents' panes are scanned with the same patterns. Question
detection is a heuristic: a message that ends with a rhetorical question is
reported, and a request phrased without a question mark or a listed phrase is
missed. The tool only reports. What to do with a finding (answer, close the
dialog, ask the owner) stays with the coordinator, who should never send a
bare Enter into a pane whose input line is not empty or dim.

Tests (ANSI fixtures: tmux captures of real Claude Code dialogs and herdr-format
captures with neutral text; a fake `herdr` for the CLI):
`cd tools/pane-watchdog && python3.14 -m unittest discover -s tests -t .`
