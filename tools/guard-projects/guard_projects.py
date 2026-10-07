"""Guards for agent shells: keep ~/projects read-only, push only to ephes/.

``guard-projects`` is a Claude Code PreToolUse hook for the Bash tool. It reads
the hook JSON on stdin and exits 2 (block, reason on stderr) when a command
would write inside the projects root. ``check-push-remote`` exits 1 unless a
remote URL belongs to the allowed GitHub owner. Python 3 stdlib only.
"""

import json
import os
import re
import shlex
import subprocess
import sys

GIT_WRITE = {
    "add", "am", "apply", "checkout", "cherry-pick", "clean", "commit", "merge",
    "mv", "pull", "rebase", "reset", "restore", "revert", "rm", "stash",
    "switch",
}
FILE_WRITE = {
    "rm", "rmdir", "mv", "touch", "mkdir", "ln", "chmod", "chown", "truncate",
    "unlink",
}
DEST_WRITE = {"cp", "rsync", "install", "tee"}  # only the destination matters
BUILD = {
    "make", "just", "npm", "pnpm", "yarn", "bun", "npx", "cargo", "uv", "pip",
    "pip3", "poetry", "pytest", "tox", "nox", "go", "xcodebuild", "swift",
    "gradle", "mvn", "molecule", "vite", "tsc",
}
SEPARATORS = {";", "&&", "||", "|", "&", "\n"}
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "exec", "xargs"}


def projects_root():
    root = os.environ.get("GUARD_PROJECTS_ROOT") or "~/projects"
    return os.path.realpath(os.path.expanduser(root))


def _expand(path, cwd):
    home = os.path.expanduser("~")
    path = re.sub(r"^(\$HOME|\$\{HOME\})(?=/|$)", home, path)
    path = os.path.expanduser(path)
    return os.path.realpath(os.path.join(cwd, path))


def _inside(path, root):
    return path == root or path.startswith(root + os.sep)


def _segments(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    seg = []
    for tok in lexer:
        if tok in SEPARATORS or set(tok) <= set(";&|") and tok:
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def blocked_reason(command, cwd, root=None):
    """Return why ``command`` would write under the projects root, or None."""
    root = root or projects_root()
    try:
        segments = list(_segments(command))
    except ValueError:
        return None  # unparseable quoting: let the shell report it
    for words in segments:
        reason, cwd = _check(words, cwd, root)
        if reason:
            return reason
    return None


def _check(words, cwd, root):
    # Redirections anywhere in the segment.
    for i, w in enumerate(words):
        if w in (">", ">>") and i + 1 < len(words):
            if _inside(_expand(words[i + 1], cwd), root):
                return f"redirects output into {words[i + 1]}", cwd
    words = [w for i, w in enumerate(words)
             if w not in (">", ">>", "<") and (i == 0 or words[i - 1] not in (">", ">>", "<"))]
    while words and ("=" in words[0] and not words[0].startswith("=")
                     or words[0] in WRAPPERS):
        words = words[1:]
    if not words:
        return None, cwd
    cmd = os.path.basename(words[0])
    args = words[1:]
    here = _inside(os.path.realpath(cwd), root)

    if cmd in ("cd", "pushd"):
        target = args[0] if args else "~"
        return None, cwd if target == "-" else _expand(target, cwd)
    if cmd in ("bash", "sh", "zsh", "fish") and "-c" in args:
        inner = args[args.index("-c") + 1] if args.index("-c") + 1 < len(args) else ""
        return blocked_reason(inner, cwd, root), cwd
    if cmd == "git":
        gitdir = cwd
        while args and args[0].startswith("-"):
            if args[0] == "-C" and len(args) > 1:
                gitdir = _expand(args[1], gitdir)
                args = args[2:]
            elif args[0] in ("-c",) and len(args) > 1:
                args = args[2:]
            else:
                args = args[1:]
        if args and args[0] in GIT_WRITE and _inside(os.path.realpath(gitdir), root):
            return f"git {args[0]} in {gitdir}", cwd
        if args and args[0] == "push":
            return _push_reason(args[1:], gitdir), cwd
        return None, cwd
    if cmd == "sed" or cmd == "perl":
        if any(a.startswith("-i") or a.startswith("--in-place") for a in args):
            for a in args:
                path = _expand(a, cwd)
                if not a.startswith("-") and _inside(path, root) and os.path.exists(path):
                    return f"{cmd} -i edits {a}", cwd
        return None, cwd
    if cmd in FILE_WRITE:
        for a in args:
            if not a.startswith("-") and _inside(_expand(a, cwd), root):
                return f"{cmd} {a}", cwd
        return None, cwd
    if cmd in DEST_WRITE:
        targets = [a for a in args if not a.startswith("-")]
        if cmd != "tee":
            targets = targets[-1:]
        for a in targets:
            if _inside(_expand(a, cwd), root):
                return f"{cmd} writes to {a}", cwd
        return None, cwd
    if cmd in BUILD and here:
        return f"{cmd} runs in {cwd} and writes build output there", cwd
    return None, cwd


def owner_ok(url, owner=None):
    owner = owner or os.environ.get("GUARD_PUSH_OWNER") or "ephes"
    pattern = (r"^(git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
               + re.escape(owner) + r"/[^/]+$")
    return re.match(pattern, url.strip()) is not None


def remote_url(remote, gitdir):
    try:
        out = subprocess.run(["git", "-C", gitdir, "remote", "get-url", remote],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _push_reason(args, gitdir):
    positional = [a for a in args if not a.startswith("-")]
    remote = positional[0] if positional else "origin"
    url = remote if ("/" in remote or ":" in remote) else remote_url(remote, gitdir)
    if url is None:
        return None  # unknown remote: git itself will fail
    if not owner_ok(url):
        return f"push target {url} is not under github.com/ephes/"
    return None


def hook_main(stdin=sys.stdin):
    try:
        data = json.load(stdin)
    except ValueError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    cwd = data.get("cwd") or os.getcwd()
    reason = blocked_reason(command, cwd)
    if reason:
        print(f"guard-projects: blocked ({reason}). ~/projects is read-only for "
              "agents and pushes go only to github.com/ephes/. Work in a "
              "worktree under ~/workspaces, or ask the owner.", file=sys.stderr)
        return 2
    return 0


def check_push_main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    remote = argv[0] if argv else "origin"
    url = remote_url(remote, os.getcwd())
    if url and owner_ok(url):
        return 0
    print(f"check-push-remote: refusing, {remote} is {url or 'missing'}, "
          "not under github.com/ephes/", file=sys.stderr)
    return 1
