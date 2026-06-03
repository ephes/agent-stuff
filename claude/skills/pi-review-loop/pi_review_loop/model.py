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
    m = _NUM_RE.search(model_part)
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split("."))


def resolve_model(list_models_output, fallback="openai-codex/gpt-5.5"):
    candidates = []
    for line in list_models_output.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        token = line.split()[0]
        if "/" not in token:
            continue
        model_part = token.rsplit("/", 1)[1].lower()
        if "gpt" not in model_part:
            continue
        candidates.append(token)
    if not candidates:
        return fallback
    return max(candidates, key=lambda t: _version_key(t.rsplit("/", 1)[1]))


def resolve_from_cli(fallback="openai-codex/gpt-5.5", timeout=30):
    """Run `pi --list-models gpt` and resolve; fall back on any failure."""
    try:
        out = subprocess.run(
            ["pi", "--list-models", "gpt"],
            capture_output=True, text=True, timeout=timeout, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return fallback
    return resolve_model(out, fallback=fallback)
