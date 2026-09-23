"""Build the one `codex exec` command the harness runs.

Every flag here is part of the review boundary, and each was checked against
the installed Codex (0.156.1) rather than assumed:

- `default_permissions` selects a named permission profile whose filesystem
  grants read access only to macOS platform paths (`:minimal`) and the
  harness-owned review root. The user's home, the repository, `/tmp`,
  `/private/tmp` and `/private/var/folders` are unreadable to every command the
  reviewer runs, writes are refused, and network is disabled. A more specific
  `read` entry wins over a broader `deny`, which is what lets a review root
  inside a temporary directory stay readable.
- `--ignore-user-config` drops the user's MCP servers, hooks, plugins and
  approval settings. It does not drop account-bound app tools, subagents or
  image generation, so those are disabled one by one below; the canary in
  `tests/test_canary.py` lists the tools the reviewer actually had.
- `code_mode_host` stays enabled: `gpt-6-sol` reaches its shell only through
  the code-mode `exec` tool, and a review without it could not read the bundle.
- `unbounded_connection_retries` is disabled so a capacity failure ends the
  turn instead of retrying forever inside the deadline.
"""
import json
import os

REVIEW_MODEL = "gpt-6-sol"
REVIEW_EFFORT = "medium"
#: The efforts a caller may ask for. The audit pins every turn to the one asked
#: for, so a run at high is proven high exactly as the default is proven medium.
REVIEW_EFFORTS = ("medium", "high")
PROFILE_NAME = "codex_review_loop"

#: Features the reviewer must not have. Each one either reaches outside the
#: review root (apps, browser, computer use, plugins, web), delegates the review
#: (multi_agent), or has no place in a read-only review (image generation,
#: goals, memories).
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


def toml_string(value):
    """A TOML basic string. JSON string escapes are a subset TOML accepts."""
    return json.dumps(value, ensure_ascii=True)


def filesystem_profile(review_root):
    root = os.path.realpath(review_root)
    entries = [(":minimal", "read")]
    entries += [(path, "deny") for path in DENIED_READ_PATHS]
    entries.append((root, "read"))
    body = ",".join(f"{toml_string(k)}={toml_string(v)}" for k, v in entries)
    return "{" + body + "}"


def codex_cmd(*, codex_bin, review_root, schema_path, last_message_path,
              instruction, effort=REVIEW_EFFORT):
    if effort not in REVIEW_EFFORTS:
        raise ValueError(f"effort {effort!r} is not one of {REVIEW_EFFORTS}")
    cmd = [
        codex_bin, "-a", "never", "exec",
        "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
        "--json",
        "-C", os.path.realpath(review_root),
        "-m", REVIEW_MODEL,
        "-c", f"model_reasoning_effort={toml_string(effort)}",
        "-c", f"default_permissions={toml_string(PROFILE_NAME)}",
        "-c", f"permissions.{PROFILE_NAME}.filesystem="
              + filesystem_profile(review_root),
        "-c", f"permissions.{PROFILE_NAME}.network.enabled=false",
        "-c", 'web_search="disabled"',
        "-c", "agents.enabled=false",
        # Commands see only the core variables (HOME, PATH, ...), on top of
        # the allowlisted environment the harness already starts Codex with.
        "-c", 'shell_environment_policy.inherit="core"',
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
