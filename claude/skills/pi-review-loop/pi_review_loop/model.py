"""Resolve the newest available GPT model id from `pi --list-models gpt` output.

Format is tolerant: take the first whitespace-delimited token on each line as a
candidate '<provider>/<model>' id, keep those whose model part contains 'gpt',
and pick the highest by the numeric version embedded in the model name. The
chosen id is passed to `--model` exactly as listed (preserving provider prefix).
"""
import re
import subprocess

_NUM_RE = re.compile(r"(\d+(?:\.\d+)*)")


def _version_key(model_part):
    # First numeric run only (e.g. gpt-5.5 -> (5,5)). This can tie variants that
    # share a major.minor (gpt-4.1 vs gpt-4.1-mini) and treats gpt-4o as (4,).
    # Acceptable for the short, filtered GPT list pi returns; re-check against
    # the real `pi --list-models gpt` output during live verification.
    m = _NUM_RE.search(model_part)
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split("."))


def resolve_model(list_models_output, fallback="openai-codex/gpt-5.5"):
    # `pi --list-models gpt` prints a whitespace table: "<provider> <model> ...",
    # with a header row. Older/other forms may print a "<provider>/<model>" token.
    # Handle both; the header row is skipped naturally (its model column is the
    # literal word "model", which contains no "gpt").
    candidates = []
    for line in list_models_output.splitlines():
        line = line.strip()
        if not line:
            continue
        tokens = line.split()
        first = tokens[0]
        if "/" in first:
            model_part = first.rsplit("/", 1)[1]
            candidate = first
        elif len(tokens) >= 2:
            provider, model_part = tokens[0], tokens[1]
            candidate = f"{provider}/{model_part}"
        else:
            continue
        if "gpt" not in model_part.lower():
            continue
        candidates.append(candidate)
    if not candidates:
        return fallback
    return max(candidates, key=lambda c: _version_key(c.rsplit("/", 1)[1]))


def resolve_from_cli(fallback="openai-codex/gpt-5.5", timeout=30):
    """Run `pi --list-models gpt` and resolve; fall back on any failure."""
    try:
        proc = subprocess.run(
            ["pi", "--list-models", "gpt"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        # pi writes the table to stderr; combine both streams so the parser
        # handles whichever stream a future version may use.
        out = proc.stdout + proc.stderr
    except (OSError, subprocess.SubprocessError):
        return fallback
    return resolve_model(out, fallback=fallback)
