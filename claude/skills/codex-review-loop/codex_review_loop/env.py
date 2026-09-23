"""Environment isolation for the Codex subprocess.

Codex reads its credentials and writes its session records under `CODEX_HOME`.
The harness reads that session record back to prove which model ran, so the
directory must be the one Codex actually used: a `CODEX_HOME` exported by an
unrelated workspace would send Codex to another account and the audit to
another directory. The value is therefore pinned rather than inherited -
`CODEX_REVIEW_HOME` when the caller deliberately sets one, otherwise
`~/.codex`.

Everything else is dropped as well. The reviewer's shell commands run under
Codex, and an environment variable is readable there whatever the filesystem
sandbox says, so the subprocess starts from an allowlist - what Codex needs to
run, authenticate over the network and find its tools - rather than from the
caller's environment minus known offenders. `OPENAI_BASE_URL` is deliberately
not on it: it would redirect the provider, and the reviewer is pinned to one
model on one provider.
"""
import os

DEFAULT_CODEX_HOME = "~/.codex"
HOME_OVERRIDE_VAR = "CODEX_REVIEW_HOME"

#: Variables passed through when present. Nothing else reaches Codex.
ALLOWED_VARS = (
    "HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "TERM", "LANG",
    "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "ALL_PROXY",
    "https_proxy", "http_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
)


def codex_home(base=None):
    source = os.environ if base is None else base
    return os.path.expanduser(source.get(HOME_OVERRIDE_VAR) or DEFAULT_CODEX_HOME)


def codex_env(base=None):
    source = os.environ if base is None else base
    env = {k: source[k] for k in ALLOWED_VARS if k in source}
    env["CODEX_HOME"] = codex_home(base=base)
    return env
