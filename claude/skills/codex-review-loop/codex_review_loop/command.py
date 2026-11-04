"""Build the one `codex exec` command the harness runs.

Every flag here is part of the review boundary, and each was checked against
the installed Codex (0.158.0) rather than assumed:

- `default_permissions` selects a named permission profile. The reviewer works
  in a throwaway copy of the repository (see `claude_review_loop.workspace`):
  the directory holding the copy, a scratch home and a scratch temporary
  directory is writable, the harness-owned review root with the bundle is
  readable, and so is the source repository's object store, which the copy
  borrows its history from. Beyond that only platform paths (`:minimal`:
  on Linux `/usr`, `/etc`, `/lib`, ...) and the toolchain that exists on this
  machine are readable, so tests can run: the prefixes `/opt/homebrew`,
  `/usr/local`, ..., plus, on Linux and outside those, the Codex install
  the harness runs, the `uv` on PATH and the target of a symlinked
  `/etc/resolv.conf` (see `toolchain_paths`). The user's home - the source
  worktree, other projects, `~/.ssh`, `~/.codex` - and the temporary
  directories stay unreadable: on macOS `/tmp`, `/private/tmp` and
  `/private/var/folders` are denied explicitly, on Linux `:minimal` never
  admits `/tmp` (see `denied_read_paths`). On macOS a more specific entry
  wins over a broader `deny`, which is what lets a run directory inside a
  temporary directory stay usable. Network is enabled, so a
  test run can fetch its dependencies.
- The reviewer's commands see `HOME` and `TMPDIR` pointed into that scratch
  space: the real home is unreadable, and git refuses to run when it cannot
  read `~/.gitconfig`.
- `--ignore-user-config` drops the user's MCP servers, hooks, plugins and
  approval settings. It does not drop account-bound app tools, subagents or
  image generation, so those are disabled one by one below; the canary in
  `tests/test_canary.py` lists the tools the reviewer actually had.
- `code_mode_host` stays enabled: `gpt-6.1-sol` reaches its shell only through
  the code-mode `exec` tool, and a review without it could not read anything.
- `unbounded_connection_retries` is disabled so a capacity failure ends the
  turn instead of retrying forever inside the deadline.
- The copy is declared an untrusted project for this one invocation. Codex
  persists `trust_level = "trusted"` for the working directory into
  `$CODEX_HOME/config.toml` whenever a run may write there and the directory
  is not already declared - with `--ignore-user-config` it never is, so every
  review used to leave an entry for its throwaway copy in the user's config.
  An explicit level in the session's own configuration stops the write
  (checked against Codex 0.160.0; a dotted `projects."<path>".trust_level`
  override does not, only a `projects` table does). Untrusted rather than
  trusted, because a trusted project loads the reviewed repository's own
  `.codex/config.toml` - its MCP servers, hooks and exec policies - which is
  repository data under review, never configuration for the reviewer.
- `--cyber-access-program` is passed only when the caller asked for one. It is
  a per-turn `codex exec` flag (Codex 0.163.0), not a `-c` key. The Daybreak
  programs are served by their own models: `gpt-6.1-sol` with
  `daybreak_blue` is refused (403 "Daybreak isn't available for this model"),
  so a Daybreak program always runs with its matching model and nothing else.
"""
import json
import os
import shutil
import sys

REVIEW_MODEL = "gpt-6.1-sol"
REVIEW_EFFORT = "high"
#: The efforts a caller may ask for. The audit pins every turn to the one asked
#: for, so a run at medium is proven medium exactly as the default is proven high.
REVIEW_EFFORTS = ("medium", "high")
PROFILE_NAME = "codex_review_loop"

#: The values of `codex exec --cyber-access-program`. Without the flag the
#: server applies its default, which the session record reports as "standard".
ACCESS_PROGRAMS = ("standard", "daybreak_blue", "daybreak_red")
#: The one model each Daybreak program runs on. Checked live on 2026-10-22:
#: `gpt-daybreak-blue-latest` answers with `daybreak_blue`; the account's
#: catalogue lists no Daybreak Red model, and `gpt-daybreak-red-latest` is
#: refused for a ChatGPT-account login.
PROGRAM_MODELS = {
    "daybreak_blue": "gpt-daybreak-blue-latest",
    "daybreak_red": "gpt-daybreak-red-latest",
}
#: Every model the harness can run, each only under its own access program.
REVIEW_MODELS = (REVIEW_MODEL,) + tuple(PROGRAM_MODELS.values())


def model_for(access_program):
    """The only model a review under `access_program` may run on: the
    program's Daybreak model, or `gpt-6.1-sol` for none or `standard`."""
    if access_program is not None and access_program not in ACCESS_PROGRAMS:
        raise ValueError(f"access program {access_program!r} is not one of "
                         f"{ACCESS_PROGRAMS}")
    return PROGRAM_MODELS.get(access_program, REVIEW_MODEL)

#: Features the reviewer must not have. Each one either reaches beyond the
#: repository copy (apps, browser, computer use, plugins, web), delegates the
#: review (multi_agent), or has no place in a review (image generation, goals,
#: memories).
DISABLED_FEATURES = (
    "apps", "browser_use", "browser_use_external", "computer_use", "goals",
    "hooks", "image_generation", "in_app_browser", "memories", "multi_agent",
    "plugins", "plugin_sharing", "realtime_conversation", "remote_plugin",
    "skill_mcp_dependency_install", "skill_search", "sleep_tool", "tool_suggest",
    "unbounded_connection_retries", "view_image", "workspace_dependencies",
    "worktrees",
)

#: Paths denied even though `:minimal` would admit them. Temporary directories
#: are where other tools leave scratch files, and on macOS `:minimal` admits
#: them.
DENIED_READ_PATHS = ("/tmp", "/private/tmp", "/private/var/folders")


def denied_read_paths(platform=None):
    """`DENIED_READ_PATHS` on macOS, nothing elsewhere. On Linux `:minimal`
    does not admit `/tmp` - the sandbox mounts an empty one holding only the
    granted paths - and a `deny` there would only do harm: Codex 0.162.1
    drops a `read` entry beneath a denied path (a `write` entry survives), so
    the review root and the source's object store under a `/tmp` run
    directory became unreadable."""
    platform = sys.platform if platform is None else platform
    return DENIED_READ_PATHS if platform == "darwin" else ()

#: Toolchain prefixes made readable when they exist, so the reviewer can run
#: git, the project's test runner and its package manager. They hold installed
#: software, not user data; `:minimal` alone admits none of them.
TOOLCHAIN_READ_PATHS = ("/opt/homebrew", "/usr/local", "/nix",
                        "/Library/Developer/CommandLineTools")

#: The manifest of Codex's self-contained install layout (`bin/codex`,
#: `codex-path/rg`, `codex-resources/bwrap`), as mise and the release archive
#: lay it out under `~/.local/share/mise/installs/codex/<version>`.
CODEX_PACKAGE_MANIFEST = "codex-package.json"
#: Tools the reviewer runs by name that may be installed as a lone binary in
#: the user's home (`~/.local/bin/uv`). Only the resolved file is granted,
#: never its directory.
TOOL_BINARIES = ("uv",)
RESOLV_CONF = "/etc/resolv.conf"


def _covered(path, prefixes):
    return any(os.path.commonpath((prefix, path)) == prefix
               for prefix in prefixes)


def codex_install_path(codex_bin, *, home="~"):
    """What must be readable for Codex to run inside its own sandbox: on
    Linux, bubblewrap re-executes the Codex binary in there, so an
    unreadable binary fails every command. The install root when the binary
    sits in Codex's package layout - unless that root is the home directory
    or holds it - otherwise only the binary itself."""
    real = os.path.realpath(codex_bin)
    root = os.path.dirname(os.path.dirname(real))
    home = os.path.realpath(os.path.expanduser(home))
    if (os.path.isfile(os.path.join(root, CODEX_PACKAGE_MANIFEST))
            and not _covered(home, [root])):
        return root
    return real


def toolchain_paths(codex_bin, *, which=shutil.which, isdir=os.path.isdir,
                    resolv_conf=RESOLV_CONF, platform=None):
    """The readable toolchain: the prefixes that exist, then, off macOS,
    what lies outside them and is needed to run - the Codex install, the
    tool binaries on PATH, and the file a symlinked `/etc/resolv.conf`
    points to (systemd-resolved keeps it under `/run`, which `:minimal`
    does not admit, and without it no name resolves). Every entry is a
    resolved path; nothing is granted because it shares a directory with
    one. On macOS the prefixes alone are what the canary verified."""
    platform = sys.platform if platform is None else platform
    paths = [os.path.realpath(p) for p in TOOLCHAIN_READ_PATHS if isdir(p)]
    if platform == "darwin":
        return paths
    extra = [codex_install_path(codex_bin)]
    for name in TOOL_BINARIES:
        found = which(name)
        if found:
            extra.append(os.path.realpath(found))
    if os.path.islink(resolv_conf):
        target = os.path.realpath(resolv_conf)
        if os.path.isfile(target):
            extra.append(target)
    for path in extra:
        if not _covered(path, paths):
            paths.append(path)
    return paths


def toml_string(value):
    """A TOML basic string. JSON string escapes are a subset TOML accepts."""
    return json.dumps(value, ensure_ascii=True)


def filesystem_profile(*, review_root, workspace_root, source_objects,
                       codex_bin, toolchain=None, platform=None):
    if toolchain is None:
        toolchain = toolchain_paths(codex_bin, platform=platform)
    entries = [(":minimal", "read")]
    entries += [(path, "deny") for path in denied_read_paths(platform)]
    entries += [(os.path.realpath(path), "read") for path in toolchain]
    entries.append((os.path.realpath(review_root), "read"))
    entries.append((os.path.realpath(source_objects), "read"))
    entries.append((os.path.realpath(workspace_root), "write"))
    body = ",".join(f"{toml_string(k)}={toml_string(v)}" for k, v in entries)
    return "{" + body + "}"


def project_trust(path):
    """The `-c` override that declares `path` an untrusted project, so Codex
    neither loads its project configuration nor persists trust for it."""
    key = toml_string(os.path.realpath(path))
    return f'projects={{{key}={{trust_level="untrusted"}}}}'


def codex_cmd(*, codex_bin, review_root, copy, schema_path, last_message_path,
              instruction, effort=REVIEW_EFFORT, model=None,
              access_program=None, toolchain=None, platform=None):
    """`copy` is the prepared `workspace.ReviewCopy`; the reviewer starts in
    its worktree. `model` defaults to the one `access_program` requires and
    must equal it."""
    if effort not in REVIEW_EFFORTS:
        raise ValueError(f"effort {effort!r} is not one of {REVIEW_EFFORTS}")
    required = model_for(access_program)
    if model is None:
        model = required
    if model != required:
        raise ValueError(f"model {model!r} cannot run under access program "
                         f"{access_program!r}; it requires {required!r}")
    profile = filesystem_profile(
        review_root=review_root, workspace_root=copy.root,
        source_objects=copy.source_objects, codex_bin=codex_bin,
        toolchain=toolchain, platform=platform)
    cmd = [
        codex_bin, "-a", "never", "exec",
        "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
        "--json",
        "-C", os.path.realpath(copy.path),
        "-m", model,
        "-c", f"model_reasoning_effort={toml_string(effort)}",
        "-c", f"default_permissions={toml_string(PROFILE_NAME)}",
        "-c", f"permissions.{PROFILE_NAME}.filesystem=" + profile,
        "-c", f"permissions.{PROFILE_NAME}.network.enabled=true",
        "-c", 'web_search="disabled"',
        "-c", "agents.enabled=false",
        # Commands see only the core variables (HOME, PATH, ...), on top of
        # the allowlisted environment the harness already starts Codex with.
        "-c", 'shell_environment_policy.inherit="core"',
        "-c", "shell_environment_policy.set.HOME="
              + toml_string(os.path.realpath(copy.home)),
        "-c", "shell_environment_policy.set.TMPDIR="
              + toml_string(os.path.realpath(copy.tmp)),
        "-c", project_trust(copy.path),
        "-c", "project_doc_max_bytes=0",
        "-c", "skills.include_instructions=false",
        "-c", "include_apps_instructions=false",
        "-c", "include_collaboration_mode_instructions=false",
        "-c", f"developer_instructions={toml_string(instruction)}",
    ]
    if access_program is not None:
        cmd += ["--cyber-access-program", access_program]
    for feature in DISABLED_FEATURES:
        cmd += ["--disable", feature]
    # The prompt arrives on stdin: passed as an argument it has silently hung.
    cmd += ["--output-schema", schema_path, "-o", last_message_path, "-"]
    return cmd
