#!/usr/bin/env bash
# gather-changes.sh - collect uncommitted change summaries across repos.
# Usage: gather-changes.sh [extra-repo-path ...]
#
# Prints git status and diff stats for the current repo and any additional
# repo paths passed as arguments. Designed to be called by the review-handoff
# skill to give the agent a unified view before drafting a reviewer prompt.

set -euo pipefail

gather_repo() {
  local repo_path="$1"
  local label

  # Use tilde-relative path for display.
  label="${repo_path/#$HOME/~}"

  if [[ ! -d "$repo_path/.git" ]] && ! git -C "$repo_path" rev-parse --git-dir &>/dev/null; then
    echo "WARNING: $label is not a git repository - skipping"
    echo ""
    return
  fi

  echo "=== $label ==="
  echo ""

  local status
  status=$(git -C "$repo_path" status --short 2>/dev/null)

  if [[ -z "$status" ]]; then
    echo "  (clean - no uncommitted changes)"
    echo ""
    return
  fi

  echo "Status:"
  echo "$status" | sed 's/^/  /'
  echo ""

  echo "Diff stat:"
  git -C "$repo_path" diff --stat 2>/dev/null | sed 's/^/  /'

  local staged
  staged=$(git -C "$repo_path" diff --cached --stat 2>/dev/null)
  if [[ -n "$staged" ]]; then
    echo ""
    echo "Staged diff stat:"
    echo "$staged" | sed 's/^/  /'
  fi

  echo ""
}

gather_repo "$(pwd)"

for extra in "$@"; do
  if [[ -d "$extra" ]]; then
    gather_repo "$extra"
  else
    echo "WARNING: $extra does not exist - skipping"
    echo ""
  fi
done
