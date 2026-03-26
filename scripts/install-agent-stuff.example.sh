#!/usr/bin/env bash

set -euo pipefail

# Example installer invoked by a private chezmoi-managed wrapper.
# This script is intentionally conservative: it shows the structure,
# not a fully opinionated install for every agent.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

install_dir() {
  local source_dir="$1"
  local target_dir="$2"

  if [[ ! -d "$source_dir" ]]; then
    return 0
  fi

  mkdir -p "$target_dir"

  # Keep the example non-destructive by default.
  # Private overlays or pre-existing local assets in the target directory
  # should not be removed by a starter script.
  rsync -a --exclude='.gitkeep' "$source_dir"/ "$target_dir"/
}

# Example targets. Adjust these from private chezmoi-managed glue.
install_dir "$repo_root/codex/skills" "$HOME/.codex/skills"
install_dir "$repo_root/claude/skills" "$HOME/.claude/skills"
install_dir "$repo_root/claude/commands" "$HOME/.claude/commands"
install_dir "$repo_root/pi/skills" "$HOME/.pi/agent/skills"

echo "agent-stuff example install complete"
