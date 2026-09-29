"""Build the one `codex exec` command the harness runs.

Every flag here is part of the review boundary, and each was checked against
the installed Codex (0.158.0) rather than assumed:

- `default_permissions` selects a named permission profile. The reviewer works
  in a throwaway copy of the repository (see `claude_review_loop.workspace`):
  the directory holding the copy, a scratch home and a scratch temporary
  directory is writable, the harness-owned review root with the bundle is
  readable, and so is the source repository's object store, which the copy
  borrows its history from. Beyond that only macOS platform paths
  (`:minimal`) and the toolchain prefixes that exist on this machine
  (`/opt/homebrew`, `/usr/local`, ...) are readable, so tests can run. The
  user's home - the source worktree, other projects, `~/.ssh`, `~/.codex` -
  `/tmp`, `/private/tmp` and `/private/var/folders` stay unreadable. A more
  specific entry wins over a broader `deny`, which is what lets a run
  directory inside a temporary directory stay usable. Network is enabled, so a
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
"""
import json
import os

REVIEW_MODEL = "gpt-6.1-sol"
REVIEW_EFFORT = "medium"
#: The efforts a caller may ask for. The audit pins every turn to the one asked
#: for, so a run at high is proven high exactly as the default is proven medium.
REVIEW_EFFORTS = ("medium", "high")
PROFILE_NAME = "codex_review_loop"

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

#: Toolchain prefixes made readable when they exist, so the reviewer can run
#: git, the project's test runner and its package manager. They hold installed
#: software, not user data; `:minimal` alone admits none of them.
TOOLCHAIN_READ_PATHS = ("/opt/homebrew", "/usr/local", "/nix",
                        "/Library/Developer/CommandLineTools")


def toml_string(value):
    """A TOML basic string. JSON string escapes are a subset TOML accepts."""
    return json.dumps(value, ensure_ascii=True)


def filesystem_profile(*, review_root, workspace_root, source_objects,
                       toolchain=None):
    if toolchain is None:
        toolchain = [p for p in TOOLCHAIN_READ_PATHS if os.path.isdir(p)]
    entries = [(":minimal", "read")]
    entries += [(path, "deny") for path in DENIED_READ_PATHS]
    entries += [(os.path.realpath(path), "read") for path in toolchain]
    entries.append((os.path.realpath(review_root), "read"))
    entries.append((os.path.realpath(source_objects), "read"))
    entries.append((os.path.realpath(workspace_root), "write"))
    body = ",".join(f"{toml_string(k)}={toml_string(v)}" for k, v in entries)
    return "{" + body + "}"


def codex_cmd(*, codex_bin, review_root, copy, schema_path, last_message_path,
              instruction, effort=REVIEW_EFFORT, toolchain=None):
    """`copy` is the prepared `workspace.ReviewCopy`; the reviewer starts in
    its worktree."""
    if effort not in REVIEW_EFFORTS:
        raise ValueError(f"effort {effort!r} is not one of {REVIEW_EFFORTS}")
    profile = filesystem_profile(
        review_root=review_root, workspace_root=copy.root,
        source_objects=copy.source_objects, toolchain=toolchain)
    cmd = [
        codex_bin, "-a", "never", "exec",
        "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
        "--json",
        "-C", os.path.realpath(copy.path),
        "-m", REVIEW_MODEL,
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
        "-c", "project_doc_max_bytes=0",
        "-c", "skills.include_instructions=false",
        "-c", "include_apps_instructions=false",
        "-c", "include_collaboration_mode_instructions=false",
        "-c", f"developer_instructions={toml_string(instruction)}",
    ]
    for feature in DISABLED_FEATURES:
        cmd += ["--disable", feature]
    # The prompt arrives on stdin: passed as an argument it has silently hung.
    cmd += ["--output-schema", schema_path, "-o", last_message_path, "-"]
    return cmd
