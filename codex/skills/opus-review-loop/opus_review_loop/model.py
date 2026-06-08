"""Resolve the Claude Code model alias used by the Opus review harness."""


DEFAULT_MODEL = "opus"


def resolve_model(value=None, fallback=DEFAULT_MODEL):
    """Return an explicit model value or the default Claude Code Opus alias."""
    return value or fallback


def resolve_from_cli(fallback=DEFAULT_MODEL):
    """Keep the harness interface without shelling out for model discovery."""
    return fallback
