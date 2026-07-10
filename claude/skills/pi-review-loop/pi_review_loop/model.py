"""Resolve the newest available GPT model id from `pi --list-models gpt` output.

Format is tolerant: take the first whitespace-delimited token on each line as a
candidate '<provider>/<model>' id, keep those whose model part contains 'gpt',
and pick the highest by the numeric version embedded in the model name. Prefer
the Sol variant when the numeric version ties. The chosen id is passed to
`--model` exactly as listed (preserving provider prefix).
"""
import re
import subprocess

DEFAULT_MODEL = "openai-codex/gpt-5.6-sol"


class PiUnavailable(RuntimeError):
    """Raised when Pi cannot list usable models in this environment."""

_NUM_RE = re.compile(r"(\d+(?:\.\d+)*)")
_PROVIDER_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MODEL_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PROVIDER_MODEL_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.:-]*$"
)
_THINKING_SUFFIX_RE = re.compile(
    r":(?:off|minimal|low|medium|high|xhigh|max)$", re.IGNORECASE
)


def _version_key(model_part):
    # First numeric run only (e.g. gpt-5.6-sol -> (5,6)). Prefer Sol when
    # variants share a version. Other same-version variants still tie and keep
    # listing order; a newer numeric version always wins, regardless of variant.
    m = _NUM_RE.search(model_part)
    if not m:
        return ((0,), 0)
    version = tuple(int(x) for x in m.group(1).split("."))
    return (version, int(model_part.lower().endswith("-sol")))


def resolve_model(list_models_output, fallback=DEFAULT_MODEL):
    # `pi --list-models gpt` prints a whitespace table: "<provider> <model> ...",
    # with a header row. Older/other forms may print a "<provider>/<model>" token.
    # Handle both; the header row is skipped naturally (its model column is the
    # literal word "model", which contains no "gpt").
    candidates = []
    saw_table_header = False
    for line in list_models_output.splitlines():
        line = line.strip()
        if not line:
            continue
        tokens = line.split()
        first = tokens[0]
        if len(tokens) >= 2 and tokens[0] == "provider" and tokens[1] == "model":
            saw_table_header = True
            continue
        if _PROVIDER_MODEL_RE.match(first):
            model_part = first.rsplit("/", 1)[1]
            candidate = first
        elif (saw_table_header and len(tokens) >= 2 and
              _PROVIDER_TOKEN_RE.match(tokens[0]) and
              _MODEL_TOKEN_RE.match(tokens[1])):
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


def _diagnose_unavailable(output):
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if "No models available" in line:
            return (
                "pi reports no available models; run `pi` and use /login, or provide "
                "a provider API key in this environment"
            )
        if "No API key found" in line:
            return line
    return None


def _summarize_output(output, limit=600):
    output = output.strip()
    if len(output) <= limit:
        return output
    return output[-limit:]


def _has_any_model(list_models_output):
    saw_table_header = False
    for line in list_models_output.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if len(tokens) >= 2 and tokens[0] == "provider" and tokens[1] == "model":
            saw_table_header = True
            continue
        if _PROVIDER_MODEL_RE.match(tokens[0]):
            return True
        if (saw_table_header and len(tokens) >= 2 and
                _PROVIDER_TOKEN_RE.match(tokens[0]) and
                _MODEL_TOKEN_RE.match(tokens[1])):
            return True
    return False


def resolve_from_cli(fallback=DEFAULT_MODEL, timeout=30,
                     require_available=False):
    """Run `pi --list-models gpt` and resolve a GPT model id.

    By default this preserves the historical fallback behavior for callers that
    want a best-effort model id. When `require_available` is true, missing
    credentials or an empty model list raise `PiUnavailable` so review harnesses
    fail before spawning a doomed Pi run.
    """
    try:
        proc = subprocess.run(
            ["pi", "--list-models", "gpt"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        # pi writes the table to stderr; combine both streams so the parser
        # handles whichever stream a future version may use.
        out = proc.stdout + proc.stderr
    except OSError as e:
        if require_available:
            raise PiUnavailable(f"cannot execute pi: {e}") from e
        return fallback
    except subprocess.SubprocessError as e:
        if require_available:
            raise PiUnavailable(f"cannot list Pi models: {e}") from e
        return fallback
    if proc.returncode != 0:
        if require_available:
            detail = _summarize_output(out)
            msg = f"`pi --list-models gpt` failed with exit {proc.returncode}"
            if detail:
                msg = f"{msg}: {detail}"
            raise PiUnavailable(msg)
        return fallback
    resolved = resolve_model(out, fallback=None)
    if resolved is not None:
        return resolved
    availability_error = _diagnose_unavailable(out)
    if availability_error:
        if require_available:
            raise PiUnavailable(availability_error)
        return fallback
    if require_available:
        detail = _summarize_output(out)
        msg = "pi listed models, but no GPT model was available"
        if detail:
            msg = f"{msg}: {detail}"
        raise PiUnavailable(msg)
    return fallback


def ensure_available(timeout=30):
    """Raise if Pi cannot list any usable model in this environment."""
    try:
        proc = subprocess.run(
            ["pi", "--list-models"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        out = proc.stdout + proc.stderr
    except OSError as e:
        raise PiUnavailable(f"cannot execute pi: {e}") from e
    except subprocess.SubprocessError as e:
        raise PiUnavailable(f"cannot list Pi models: {e}") from e
    if proc.returncode != 0:
        detail = _summarize_output(out)
        msg = f"`pi --list-models` failed with exit {proc.returncode}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PiUnavailable(msg)
    if _has_any_model(out):
        return
    availability_error = _diagnose_unavailable(out)
    if availability_error:
        raise PiUnavailable(availability_error)
    raise PiUnavailable("pi listed no usable models")


def ensure_model_available(model_pattern, timeout=30):
    """Raise unless Pi lists a model matching the requested pattern or id."""
    lookup = _THINKING_SUFFIX_RE.sub("", model_pattern)
    try:
        proc = subprocess.run(
            ["pi", "--list-models", lookup],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        out = proc.stdout + proc.stderr
    except OSError as e:
        raise PiUnavailable(f"cannot execute pi: {e}") from e
    except subprocess.SubprocessError as e:
        raise PiUnavailable(f"cannot list Pi models: {e}") from e
    if proc.returncode != 0:
        detail = _summarize_output(out)
        msg = f"`pi --list-models {lookup}` failed with exit {proc.returncode}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PiUnavailable(msg)
    if _has_any_model(out):
        return
    availability_error = _diagnose_unavailable(out)
    if availability_error:
        raise PiUnavailable(availability_error)
    raise PiUnavailable(f"requested model is not available: {model_pattern}")
