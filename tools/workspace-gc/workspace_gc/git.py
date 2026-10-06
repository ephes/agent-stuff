"""Thin, read-mostly wrappers around the git CLI.

Every call runs non-interactively (no credential prompt, ssh in batch mode)
and with GIT_OPTIONAL_LOCKS=0, so a status check does not rewrite the index of
a checkout it only inspects.
"""

from __future__ import annotations

import os
import subprocess
import threading

LS_REMOTE_TIMEOUT = 45
GIT_TIMEOUT = 120


class GitError(Exception):
    pass


_env_lock = threading.Lock()
_base_env: dict[str, str] | None = None


def base_env() -> dict[str, str]:
    global _base_env
    with _env_lock:
        if _base_env is None:
            env = dict(os.environ)
            env["GIT_OPTIONAL_LOCKS"] = "0"
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GCM_INTERACTIVE"] = "never"
            env["LC_ALL"] = "C"
            # Replacement refs could make an unpushed commit look contained.
            env["GIT_NO_REPLACE_OBJECTS"] = "1"
            env.pop("GIT_DIR", None)
            env.pop("GIT_WORK_TREE", None)
            env.pop("GIT_INDEX_FILE", None)
            env.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
            if "GIT_SSH_COMMAND" not in env and not _configured_ssh_command(env):
                env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=15"
            _base_env = env
        return dict(_base_env)


def _configured_ssh_command(env: dict[str, str]) -> bool:
    try:
        out = subprocess.run(
            ["git", "config", "--global", "--get", "core.sshCommand"],
            env=env, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def run(args: list[str], cwd: str | None = None, *, input: str | None = None,
        alternates: list[str] | None = None, check: bool = True,
        timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    env = base_env()
    if alternates:
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(alternates)
    # A file-system monitor or untracked cache could hide changes from status.
    cmd = ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false"]
    if cwd is not None:
        cmd += ["-C", cwd]
    cmd += args
    try:
        proc = subprocess.run(cmd, env=env, input=input, capture_output=True,
                              text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"timed out: git {' '.join(args[:2])}") from exc
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        raise GitError(f"git {' '.join(args[:2])}: {msg[-1] if msg else proc.returncode}")
    return proc


def out(args: list[str], cwd: str | None = None, **kw) -> str:
    return run(args, cwd, **kw).stdout


def is_network_url(url: str) -> bool:
    """True for URLs that reach another host (ssh, https, git, scp-like).

    Local paths, file:// URLs and relative paths are local remotes whose own
    remotes must be followed instead.
    """
    u = url.strip()
    if not u:
        return False
    if u.startswith("file://"):
        return False
    if "://" in u:
        return True
    if u.startswith(("/", ".", "~")):
        return False
    # scp-like syntax: [user@]host:path, where no slash precedes the colon
    colon = u.find(":")
    slash = u.find("/")
    return colon > 0 and (slash == -1 or colon < slash)


def local_url_path(url: str, repo: str) -> str:
    u = url.strip()
    if u.startswith("file://"):
        u = u[len("file://"):]
    u = os.path.expanduser(u)
    if not os.path.isabs(u):
        u = os.path.join(repo, u)
    return os.path.normpath(u)


def ls_remote(url: str, cwd: str | None = None) -> set[str]:
    """Commit-ish object names of every branch and tag on `url`."""
    text = out(["ls-remote", "--heads", "--tags", url], cwd, timeout=LS_REMOTE_TIMEOUT)
    shas = set()
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and len(parts[0]) >= 40:
            shas.add(parts[0])
    return shas
