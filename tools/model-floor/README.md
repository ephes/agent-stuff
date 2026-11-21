# model-floor

<!-- model-floor: allow-file - this page lists refused ids as examples. -->

Reports OpenAI model ids below GPT-6.2 in active configuration. Owner rule
(2026-11-18): no OpenAI model older than 6.2 is used anywhere in the agent
tooling. Python 3 stdlib only.

```sh
tools/model-floor/bin/model-floor-check .                     # this repository
tools/model-floor/bin/model-floor-check ~/.local/share/chezmoi --allow 'private_dot_config/emerge/coordination/reports/*'
tools/model-floor/bin/model-floor-check path/to/run.sh path/to/COMMON.md   # single files
```

Output: one line per finding, `path:line: id: text`. Exit 0 clean, 1 findings,
2 a path that does not exist.
Diagnostic paths escape backslashes (except on Windows, where they separate
path components), non-printable characters and undecodable filename bytes
(shown as filesystem surrogate escapes such as `\udcff`).

## What counts

Every numbered GPT id older than 6.2, case-insensitive, with or without a
provider prefix: `gpt-6.1-sol`, `gpt-6-astra`, `GPT-6 Sol`, `openai/gpt-5.6`,
`gpt-4o-mini-transcribe`. Ids at or above the floor (`gpt-6.2-sol`,
`gpt-6.2-astra`, `gpt-7`) and unnumbered ids (`gpt-daybreak-blue-latest`,
`codex-auto-review`) are not reported.

Major and minor components are compared numerically, including long digit
sequences, leading zeros, and Unicode decimal digits.

Only `gpt-<number>` ids are recognized. Older OpenAI families without that
form - the o-series (`o3`, `o4-mini`), `codex-mini-latest`, spellings such as
`gpt5` or `GPT 6.1` - pass unreported, because their short names collide with
ordinary text. A clean result therefore proves the absence of old `gpt-N`
ids, not of every older OpenAI model; the review harnesses themselves accept
only their pinned model, so no unnumbered id can run a review.

## What is history

Model ids in history name what ran at that time and stay as written:

- `CHANGELOG*` anywhere, `docs/archive/`, `docs/plans/`, `docs/specs/` and
  `docs/review-cycle-log.md` (paths relative to the scanned directory);
- the globs in a `.model-floor-allow` file at the scanned directory (one per
  line, `#` comments) and in `--allow GLOB` arguments;
- a line carrying `model-floor: allow` (a test fixture that proves an old id
  is refused);
- a file whose first five lines carry `model-floor: allow-file`.

At the top of a git checkout only tracked and new, not ignored files are
scanned (`git ls-files --cached --others --exclude-standard`), so local
scratch output that `.gitignore` covers does not count. Git path records
retain their original bytes under the platform's filesystem encoding policy.
Elsewhere the whole tree is walked, skipping `.git`, virtual environments,
`node_modules` and caches. Binary files and files over 2 MB are skipped
everywhere.

## Tests

```sh
cd tools/model-floor && python3.14 -m unittest discover -s tests -t .
```

`tests/test_model_floor.py::TestRepository` runs the check over the whole
agent-stuff checkout, so the suite fails as soon as a pre-6.2 id lands outside
history.
