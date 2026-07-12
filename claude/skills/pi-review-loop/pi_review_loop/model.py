"""Resolve the single approved Pi code-review model.

Pi is only a transport for the OpenAI Codex subscription-backed GPT reviewer.
Claude/Anthropic, local models, OpenRouter, and other providers are deliberately
rejected instead of being treated as fallbacks.
"""
import re
import subprocess

DEFAULT_MODEL = "openai-codex/gpt-5.6-sol"


class PiUnavailable(RuntimeError):
    """Raised when Pi cannot list usable models in this environment."""

_PROVIDER_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MODEL_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PROVIDER_MODEL_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.:-]*$"
)
_THINKING_SUFFIX_RE = re.compile(
    r":(?:off|minimal|low|medium|high|xhigh|max)$", re.IGNORECASE
)


def resolve_model(list_models_output, fallback=DEFAULT_MODEL):
    # `pi --list-models gpt` prints a whitespace table: "<provider> <model> ...",
    # with a header row. Older/other forms may print a "<provider>/<model>" token.
    # Handle both. Selection below is an exact match, so headers and every
    # non-approved model are ignored.
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
        if candidate == DEFAULT_MODEL:
            return candidate
    return fallback


def validate_review_model(model_pattern):
    """Return the normalized model or reject every non-approved review route."""
    lookup = _THINKING_SUFFIX_RE.sub("", model_pattern)
    if lookup != DEFAULT_MODEL:
        raise PiUnavailable(
            f"unsupported Pi review model: {model_pattern}; mandatory Pi reviews "
            f"use {DEFAULT_MODEL} only (no Claude/Anthropic, local models, "
            "OpenRouter, or automatic provider fallback)"
        )
    return lookup


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


def resolve_from_cli(fallback=DEFAULT_MODEL, timeout=30,
                     require_available=False):
    """Run `pi --list-models gpt` and resolve the approved GPT model id.

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
        msg = f"pi listed models, but required review model {DEFAULT_MODEL} was unavailable"
        if detail:
            msg = f"{msg}: {detail}"
        raise PiUnavailable(msg)
    return fallback


def ensure_available(timeout=30):
    """Raise unless Pi lists the single approved code-review model."""
    resolve_from_cli(timeout=timeout, require_available=True)


def ensure_model_available(model_pattern, timeout=30):
    """Raise unless the requested model is approved and listed by Pi."""
    lookup = validate_review_model(model_pattern)
    try:
        proc = subprocess.run(
            ["pi", "--list-models", "gpt"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        out = proc.stdout + proc.stderr
    except OSError as e:
        raise PiUnavailable(f"cannot execute pi: {e}") from e
    except subprocess.SubprocessError as e:
        raise PiUnavailable(f"cannot list Pi models: {e}") from e
    if proc.returncode != 0:
        detail = _summarize_output(out)
        msg = f"`pi --list-models gpt` failed with exit {proc.returncode}"
        if detail:
            msg = f"{msg}: {detail}"
        raise PiUnavailable(msg)
    if resolve_model(out, fallback=None) == DEFAULT_MODEL:
        return lookup
    availability_error = _diagnose_unavailable(out)
    if availability_error:
        raise PiUnavailable(availability_error)
    raise PiUnavailable(f"requested model is not available: {model_pattern}")
