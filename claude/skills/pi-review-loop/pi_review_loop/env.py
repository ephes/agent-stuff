"""Environment isolation for every Pi subprocess.

Pi keeps its credential store and provider configuration in its agent
directory. A `PI_CODING_AGENT_DIR` exported by an unrelated workspace makes Pi
load that other application's directory instead: observed failures include Pi
reading a foreign `auth.json` schema and crashing during provider discovery,
and Pi loading another workspace's account so the approved review model was
never listed. Both blocked the gate before any reviewer started.

Review subprocesses therefore never inherit that variable. They run against an
explicit agent directory: `PI_REVIEW_AGENT_DIR` when the caller deliberately
sets one, otherwise `~/.pi/agent`.
"""
import os

DEFAULT_AGENT_DIR = "~/.pi/agent"

#: Cross-workspace variables that must never reach a review subprocess by
#: inheritance. `CODEX_HOME` is dropped for the same reason: a stale value from
#: another workspace has redirected Pi's Codex-provider configuration.
STRIPPED_VARS = ("PI_CODING_AGENT_DIR", "CODEX_HOME")

#: Deliberate, review-scoped override for the pinned agent directory.
AGENT_DIR_OVERRIDE_VAR = "PI_REVIEW_AGENT_DIR"


def agent_dir(base=None):
    """Return the agent directory review subprocesses must use."""
    source = os.environ if base is None else base
    override = source.get(AGENT_DIR_OVERRIDE_VAR)
    return os.path.expanduser(override or DEFAULT_AGENT_DIR)


def pi_env(overrides=None, base=None):
    """Build the environment for a Pi subprocess.

    Starts from the current environment so PATH and terminal settings survive,
    strips inherited cross-workspace agent variables, pins the agent directory,
    and applies the harness defaults. `overrides` wins over all of it.
    """
    env = dict(os.environ if base is None else base)
    for var in STRIPPED_VARS:
        env.pop(var, None)
    env["PI_CODING_AGENT_DIR"] = agent_dir(base=base)
    env["PI_SKIP_VERSION_CHECK"] = "1"
    env["PI_TELEMETRY"] = "0"
    if overrides:
        env.update(overrides)
    return env
