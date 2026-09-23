"""Resolve the Claude model the review harness runs."""


# Pinned to a model id rather than the `opus` alias, so the default reviewer and
# its default effort change together, deliberately, instead of whenever the
# alias moves.
DEFAULT_MODEL = "claude-opus-5-5"


def resolve_model(value=None, fallback=DEFAULT_MODEL):
    """Return an explicit model value or the default Claude model."""
    return value or fallback


def resolve_from_cli(fallback=DEFAULT_MODEL):
    """Keep the harness interface without shelling out for model discovery."""
    return fallback
