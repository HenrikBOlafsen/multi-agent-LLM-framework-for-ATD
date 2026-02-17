#!/usr/bin/env bash
set -euo pipefail

CFG="${1:-pipeline.yaml}"

REPOS_FILE="$(python3 - <<'PY' "$CFG"
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1], "r")) or {}
print(cfg["repos_file"])
PY
)"

echo "== Cleaning old repo worktrees =="
while read -r repo base entry lang; do
  [[ -z "${repo:-}" ]] && continue
  [[ "$repo" =~ ^# ]] && continue

  repo_dir="projects_to_analyze/$repo"
  wt="$repo_dir/.atd_worktrees"

  # Legacy cleanup only. Ignore all failures.
  rm -rf "$wt" >/dev/null 2>&1 || true
  git -C "$repo_dir" worktree prune >/dev/null 2>&1 || true
done < "$REPOS_FILE"
