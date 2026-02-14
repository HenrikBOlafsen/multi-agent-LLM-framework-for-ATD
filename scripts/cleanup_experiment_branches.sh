#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   cleanup_experiment_branches.sh <repo_dir> <branch_prefix>
#
# Example:
#   cleanup_experiment_branches.sh /workspace/projects_to_analyze/jinja atd-sim_ok_smoke_realish-explain_multiAgent

usage() { echo "usage: $0 <repo_dir> <branch_prefix>"; exit 2; }
[ $# -eq 2 ] || usage

REPO_DIR="$(cd "$1" && pwd)"
PREFIX="$2"

[ -d "$REPO_DIR/.git" ] || { echo "Not a git repo: $REPO_DIR" >&2; exit 3; }

echo "== Cleanup branches in $(basename "$REPO_DIR") matching prefix: $PREFIX =="

# 1) Remove any lingering worktrees created under .atd_worktrees (safe, local only)
WT_ROOT="$REPO_DIR/.atd_worktrees"
if [ -d "$WT_ROOT" ]; then
  # Ask git what worktrees exist, remove those under WT_ROOT
  while IFS= read -r wt; do
    [ -z "$wt" ] && continue
    # Only remove those under WT_ROOT
    case "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$wt")" in
      "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$WT_ROOT")"/*)
        echo "Removing worktree: $wt"
        git -C "$REPO_DIR" worktree remove --force "$wt" >/dev/null 2>&1 || true
        rm -rf "$wt" >/dev/null 2>&1 || true
        ;;
    esac
  done < <(git -C "$REPO_DIR" worktree list --porcelain | awk '$1=="worktree"{print $2}')
  git -C "$REPO_DIR" worktree prune >/dev/null 2>&1 || true
fi

# 2) Make sure we’re not currently on a branch we’re about to delete
# If current branch matches prefix, switch to a safe baseline (prefer main, else master, else detached).
cur_branch="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD || echo HEAD)"
if [[ "$cur_branch" != "HEAD" && "$cur_branch" == "$PREFIX"* ]]; then
  if git -C "$REPO_DIR" show-ref --verify --quiet refs/heads/main; then
    git -C "$REPO_DIR" checkout -q main
  elif git -C "$REPO_DIR" show-ref --verify --quiet refs/heads/master; then
    git -C "$REPO_DIR" checkout -q master
  else
    git -C "$REPO_DIR" checkout -q --detach
  fi
fi

# 3) Delete local branches matching the prefix
mapfile -t branches < <(git -C "$REPO_DIR" for-each-ref --format='%(refname:short)' refs/heads | grep -E "^${PREFIX}" || true)

if [ "${#branches[@]}" -eq 0 ]; then
  echo "No branches matched."
else
  echo "Deleting ${#branches[@]} branches..."
  for b in "${branches[@]}"; do
    echo "  -D $b"
    git -C "$REPO_DIR" branch -D "$b" >/dev/null 2>&1 || true
  done
fi

# 4) Optional: expire reflog + aggressive GC if you want to reclaim disk immediately
# Uncomment if you care about disk usage during large runs:
# git -C "$REPO_DIR" reflog expire --expire=now --all || true
# git -C "$REPO_DIR" gc --prune=now --aggressive || true

echo "✅ Cleanup done."
