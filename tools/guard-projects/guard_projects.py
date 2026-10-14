"""Guards for agent shells: keep ~/projects read-only, push only to ephes/.

``guard-projects`` is a Claude Code PreToolUse hook for the Bash tool. It reads
the hook JSON on stdin and exits 2 (block, reason on stderr) when a command
would write inside the projects root or push outside the allowed GitHub owner.
``check-push-remote`` exits 1 unless every URL a ``git push`` with the same
arguments would push to belongs to that owner. Push targets are resolved the
way git does; an unresolvable target is refused. Python 3 stdlib only.
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
    env = {}  # leading VAR=value assignments, applied when resolving pushes
    while words and ("=" in words[0] and not words[0].startswith("=")
                     or words[0] in WRAPPERS):
        name, _, value = words[0].partition("=")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and words[0] not in WRAPPERS:
            env[name] = value
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
        global_opts = []  # options that change which repository/config git sees
        while args and args[0].startswith("-"):
            opt, has_eq, val = args[0].partition("=")
            if opt in GIT_GLOBAL_VALUE and not has_eq:
                if len(args) < 2:
                    break
                val, args = args[1], args[2:]
            else:
                args = args[1:]
            if opt == "-C":
                gitdir = _expand(val, gitdir)
                global_opts += ["-C", gitdir]
            elif opt in ("--git-dir", "--work-tree"):
                global_opts.append(f"{opt}={_expand(val, gitdir)}")
            elif opt in ("-c", "--config-env"):
                global_opts += [opt, val]
        if args and args[0] in GIT_WRITE and _inside(os.path.realpath(gitdir), root):
            return f"git {args[0]} in {gitdir}", cwd
        if args and args[0] == "push":
            return push_reason(args[1:], cwd, global_opts, env), cwd
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


# git push options: name -> "req" (value, also as the next word), "opt" (value
# only after "="), or None (no value). Matches `git push -h` of git 2.5x.
PUSH_LONG = {
    "verbose": None, "quiet": None, "repo": "req", "all": None,
    "branches": None, "mirror": None, "delete": None, "tags": None,
    "dry-run": None, "porcelain": None, "force": None,
    "force-with-lease": "opt", "force-if-includes": None,
    "recurse-submodules": "req", "thin": None, "receive-pack": "req",
    "exec": "req", "set-upstream": None, "progress": None, "prune": None,
    "no-verify": None, "verify": None, "follow-tags": None, "signed": "opt",
    "atomic": None, "push-option": "req", "ipv4": None, "ipv6": None,
}
PUSH_SHORT_FLAGS = set("vqdnfu46")
PUSH_SHORT_VALUE = {"o"}
# git global options whose value may be the next word.
GIT_GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                    "--config-env", "--super-prefix"}


class PushTargetError(Exception):
    """The push target could not be determined; callers fail closed."""


def _long_option(name):
    if name in PUSH_LONG:
        return name
    matches = [n for n in PUSH_LONG if n.startswith(name)]
    if name and len(matches) == 1:  # git accepts unique abbreviations
        return matches[0]
    raise PushTargetError(f"unknown or ambiguous option --{name}")


def parse_push_args(args):
    """Return the repository named by ``git push`` arguments, or None.

    The first positional argument wins over ``--repo``, as in git.
    """
    repo, positional = None, []
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        i += 1
        if a in ("--", "--end-of-options"):
            positional += args[i:]
            break
        if a.startswith("--"):
            body, has_eq, value = a[2:].partition("=")
            negated = body.startswith("no-") and body != "no-verify"
            name = _long_option(body[3:] if negated else body)
            kind = PUSH_LONG[name]
            if negated or kind is None:
                if has_eq:
                    raise PushTargetError(f"{a} takes no value")
                if negated and name == "repo":
                    repo = None
                continue
            if not has_eq and kind == "req":
                if i >= n:
                    raise PushTargetError(f"{a} needs a value")
                value, i = args[i], i + 1
            if name == "repo":
                repo = value
        elif a.startswith("-") and a != "-":
            for j, ch in enumerate(a[1:], 1):
                if ch in PUSH_SHORT_VALUE:
                    if j == len(a) - 1 and i >= n:
                        raise PushTargetError(f"-{ch} needs a value")
                    if j == len(a) - 1:
                        i += 1
                    break
                if ch not in PUSH_SHORT_FLAGS:
                    raise PushTargetError(f"unknown option -{ch}")
        else:
            positional.append(a)
    return positional[0] if positional else repo


def _git(cwd, global_opts, env, *args):
    try:
        out = subprocess.run(["git", *global_opts, *args], cwd=cwd,
                             capture_output=True, text=True, timeout=10,
                             env={**os.environ, **(env or {})})
    except (OSError, subprocess.SubprocessError) as exc:
        raise PushTargetError(f"git {args[0]} failed: {exc}") from None
    return out.returncode, out.stdout


def _config(cwd, global_opts, env, key):
    code, out = _git(cwd, global_opts, env, "config", "--get", key)
    if code == 1:
        return None
    if code != 0:
        raise PushTargetError(f"git config --get {key} failed")
    return out.strip() or None


def _default_remote(cwd, global_opts, env):
    """The remote a bare ``git push`` uses, resolved the way git does."""
    code, out = _git(cwd, global_opts, env, "symbolic-ref", "-q", "--short", "HEAD")
    branch = out.strip() if code == 0 else None
    for key in ([f"branch.{branch}.pushRemote"] if branch else []) + [
            "remote.pushDefault"] + ([f"branch.{branch}.remote"] if branch else []):
        value = _config(cwd, global_opts, env, key)
        if value:
            return value
    code, out = _git(cwd, global_opts, env, "remote")
    if code != 0:
        raise PushTargetError("git remote failed (not a repository?)")
    remotes = out.split()
    return remotes[0] if len(remotes) == 1 else "origin"


def push_urls(args, cwd, global_opts=(), env=None):
    """Every URL ``git push <args>`` run in ``cwd`` would push to.

    Named remotes use ``git remote get-url --push --all`` (pushurl, url
    rewriting); a repository that is not a configured remote is taken as a
    URL or path and rewritten the same way. Raises PushTargetError when the
    target cannot be determined.
    """
    global_opts = list(global_opts)
    repo = parse_push_args(args)
    if repo is None:
        repo = _default_remote(cwd, global_opts, env)
    if not repo:
        raise PushTargetError("empty repository")
    code, out = _git(cwd, global_opts, env, "remote", "get-url", "--push",
                     "--all", "--", repo)
    if code == 0:
        urls = [u.strip() for u in out.split("\n") if u.strip()]
    else:  # not a configured remote: git treats it as a URL or path
        urls = [_rewrite_push_url(repo, cwd, global_opts, env)]
    if not urls:
        raise PushTargetError(f"no push URL for {repo}")
    return urls


def _rewrite_push_url(url, cwd, global_opts, env):
    """Apply url.<base>.pushInsteadOf, else insteadOf, as git does for a push
    to a repository given as a URL (longest matching prefix wins)."""
    code, out = _git(cwd, global_opts, env, "config", "-z", "--get-regexp",
                     r"^url\..*\.(push)?insteadof$")
    if code not in (0, 1):
        raise PushTargetError("git config --get-regexp url.* failed")
    best = {"pushinsteadof": None, "insteadof": None}
    for entry in filter(None, out.split("\0")):
        key, _, prefix = entry.partition("\n")
        base, _, kind = key[len("url."):].rpartition(".")
        if url.startswith(prefix) and (best[kind] is None or len(prefix) > len(best[kind][0])):
            best[kind] = (prefix, base)
    match = best["pushinsteadof"] or best["insteadof"]
    return match[1] + url[len(match[0]):] if match else url


def push_reason(args, cwd, global_opts=(), env=None):
    """Why ``git push <args>`` must not run, or None when every URL is allowed."""
    try:
        urls = push_urls(args, cwd, global_opts, env)
    except PushTargetError as exc:
        return f"cannot resolve push target: {exc}"
    for url in urls:
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
    """``check-push-remote [git push arguments]``: exit 0 only when that push
    would go to github.com/ephes/ only (no arguments: a bare ``git push``)."""
    argv = sys.argv[1:] if argv is None else argv
    reason = push_reason(argv, os.getcwd())
    if reason is None:
        return 0
    print(f"check-push-remote: refusing, {reason}", file=sys.stderr)
    return 1
