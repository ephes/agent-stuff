"""Thin, read-mostly wrappers around the git CLI.

Every call runs non-interactively (no credential prompt, ssh in batch mode)
and with GIT_OPTIONAL_LOCKS=0, so a status check does not rewrite the index of
a checkout it only inspects.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit, unquote

from . import budget

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
            redirectors = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                           "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                           "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE",
                           "GIT_REPLACE_REF_BASE", "GIT_CONFIG"}
            for key in list(env):
                if key in redirectors or (key.startswith("GIT_CONFIG_") and key not in
                        {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"}):
                    env.pop(key)
            if "GIT_SSH_COMMAND" not in env and not _configured_ssh_command(env):
                # A stalled connection is dropped after ~45s without traffic.
                env["GIT_SSH_COMMAND"] = ("ssh -o BatchMode=yes -o ConnectTimeout=15 "
                                          "-o ServerAliveInterval=15 -o ServerAliveCountMax=3")
            # HTTP(S): abort a transfer slower than 1 KB/s for 30s.
            env.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", "1000")
            env.setdefault("GIT_HTTP_LOW_SPEED_TIME", "30")
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


def _stop_group(child):
    # Keep an unreaped leader while signalling, so its group id cannot be
    # recycled between graceful and final signals. Never drain inherited pipes.
    if child.returncode is not None:
        return
    try:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except OSError:
            pass  # includes macOS EPERM for a zombie-only group
        time.sleep(0.2)
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            child.kill()
        except OSError:
            pass
        child.wait(timeout=1)


def run(args: list[str], cwd: str | None = None, *, input: str | None = None,
        alternates: list[str] | None = None, check: bool = True,
        timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    # Never outlive the current step or run deadline (see budget.py).
    timeout = budget.cap(timeout)
    env = base_env()
    if alternates:
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(alternates)
    # A file-system monitor or untracked cache could hide changes from status.
    cmd = ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false"]
    if cwd is not None:
        cmd += ["-C", cwd]
    cmd += args
    try:
        child = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, errors="replace", start_new_session=True)
        try:
            try:
                stdout, stderr = child.communicate(input=input, timeout=timeout)
            except BaseException:
                try:
                    _stop_group(child)
                except (OSError, subprocess.TimeoutExpired):
                    pass  # cleanup must never replace the original interruption
                raise
            proc = subprocess.CompletedProcess(cmd, child.returncode, stdout, stderr)
        finally:
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        pass
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"timed out: git {' '.join(args[:2])[:160]}") from exc
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        raise GitError(f"git {' '.join(args[:2])[:160]}: {msg[-1][:500] if msg else proc.returncode}")
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
        try:
            parsed = urlsplit(u)
            if parsed.netloc.lower() not in ("", "localhost") or parsed.query or parsed.fragment or parsed.path.startswith("//"):
                raise ValueError("nonlocal or ambiguous file URL")
            u = unquote(parsed.path, encoding="utf-8", errors="strict")
            if "\0" in u:
                raise ValueError("NUL in file URL path")
        except ValueError as exc:
            raise GitError("unsupported local file URL") from exc
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
