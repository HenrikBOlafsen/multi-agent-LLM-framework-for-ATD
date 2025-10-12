#!/usr/bin/env bash
# Shared helpers for the quality checker scripts (no abbreviations).
set -euo pipefail

# Create a detached worktree at <label>, export WT_ROOT, and install cleanup trap.
quality_checker_prepare_worktree() {
  local repo="$1" label="$2"

  git -C "$repo" fetch --all --quiet
  if ! git -C "$repo" rev-parse --verify --quiet "${label}^{commit}" >/dev/null; then
    for r in $(git -C "$repo" remote); do
      git -C "$repo" fetch "$r" "$label:$label" && break || true
    done
  fi
  if ! git -C "$repo" rev-parse --verify --quiet "${label}^{commit}" >/dev/null; then
    echo "Error: ref '$label' not found in $repo (after fetch)." >&2
    exit 1
  fi

  local tmp; tmp="$(mktemp -d -t qualitywt.XXXXXX)"
  git -C "$repo" worktree add --detach "$tmp" "$label" >/dev/null
  WT_ROOT="$tmp"; export WT_ROOT

  # IMPORTANT: bake values into the trap to avoid unbound locals with `set -u`
  local cleanup_repo="$repo"
  local cleanup_tmp="$tmp"
  trap "git -C '$cleanup_repo' worktree remove --force '$cleanup_tmp' 2>/dev/null || true; rm -rf '$cleanup_tmp' 2>/dev/null || true" EXIT

  local sha branch
  sha="$(git -C "$WT_ROOT" rev-parse --short HEAD)"
  branch="$(git -C "$WT_ROOT" symbolic-ref --short -q HEAD || echo detached)"
  echo '==> worktree at' "$label" '@' "$sha" "(branch: $branch)"
}

# Write src_paths.txt, python_version.txt, git_sha.txt, git_branch.txt
quality_checker_write_metadata() {
  local root="$1"; shift
  local out="$1"; shift
  local -a src_paths=( "$@" )

  printf '%s\n' "${src_paths[@]}" > "$out/src_paths.txt"
  python -V > "$out/python_version.txt" || true

  git -C "$root" rev-parse --short HEAD > "$out/git_sha.txt"
  git -C "$root" branch --show-current  > "$out/git_branch.txt" || echo "detached" > "$out/git_branch.txt"
}
