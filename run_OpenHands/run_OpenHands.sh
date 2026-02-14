#!/usr/bin/env bash
set -euo pipefail

# Usage (offline/local-only):
#   run_OpenHands.sh <repo_dir> <base_branch> <new_branch> <prompt_path> <out_dir>
#
# Goals:
# - Create a fresh git worktree (no reuse) for each run
# - Run OpenHands in that worktree
# - If changes exist, commit them locally (no pushing)
# - Always write a git diff patch into the results folder (if changes exist)
# - Always remove the worktree checkout afterward to avoid accidental reuse
#   (but keep the local branch so metrics can check it out)

usage() { echo "usage: $0 <repo_dir> <base_branch> <new_branch> <prompt_path> <out_dir>"; exit 1; }
[ $# -eq 5 ] || usage

REPO_DIR="$(cd "$1" && pwd)"
BASE_BRANCH="$2"
NEW_BRANCH="$3"
PROMPT_PATH="$4"
OUT_DIR="$(mkdir -p "$5" && cd "$5" && pwd)"

[ -d "$REPO_DIR/.git" ] || { echo "Not a git repo: $REPO_DIR" >&2; exit 2; }
[ -f "$PROMPT_PATH" ] || { echo "Prompt not found: $PROMPT_PATH" >&2; exit 3; }

LLM_MODEL="${LLM_MODEL:-}"
LLM_BASE_URL="${LLM_BASE_URL:-}"
LLM_API_KEY="${LLM_API_KEY:-}"

OPENHANDS_IMAGE="${OPENHANDS_IMAGE:-docker.all-hands.dev/all-hands-ai/openhands:0.59}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-docker.all-hands.dev/all-hands-ai/runtime:0.59-nikolaik}"
MAX_ITERS="${MAX_ITERS:-100}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-Refactor: break dependency cycle}"

# Identity used for *local-only* commits.
# (These do not affect pushing; they just allow commits to be created.)
GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-atd-bot}"
GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-atd-bot@local}"
GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"

[ -n "$LLM_API_KEY" ] || { echo "LLM_API_KEY is required"; exit 5; }
[ -n "$LLM_BASE_URL" ] || { echo "LLM_BASE_URL is required"; exit 6; }
[ -n "$LLM_MODEL" ] || { echo "LLM_MODEL is required"; exit 7; }

abs() { python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"; }
ts() { date -Iseconds; }
ts_file() { date +%Y%m%d_%H%M%S; }

HOST_PWD="${HOST_PWD:-}"
if [ -z "$HOST_PWD" ]; then
  echo "ERROR: HOST_PWD is not set."
  echo "Start the dev container with:  -e HOST_PWD=\"\$(pwd)\""
  exit 9
fi
HOST_PWD="${HOST_PWD%/}"

DOCKER_SOCK_GID=""
if [ -S /var/run/docker.sock ]; then
  DOCKER_SOCK_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || true)"
fi

LLM_BASE_URL="${LLM_BASE_URL%/}"
LLM_BASE_URL_OH="$LLM_BASE_URL"
if [[ "$LLM_BASE_URL_OH" != */v1 ]]; then
  LLM_BASE_URL_OH="${LLM_BASE_URL_OH}/v1"
fi

MODEL_FOR_OH="$LLM_MODEL"
if [[ "$MODEL_FOR_OH" == /* ]]; then
  MODEL_FOR_OH="openai/${MODEL_FOR_OH}"
elif [[ "$MODEL_FOR_OH" != openai/* ]]; then
  MODEL_FOR_OH="openai/${MODEL_FOR_OH}"
fi

PROMPT_ABS="$(abs "$PROMPT_PATH")"
PROMPT_DIR="$(dirname "$PROMPT_ABS")"
PROMPT_BASENAME="$(basename "$PROMPT_ABS")"
PROMPT_IN_CONTAINER="/prompts/$PROMPT_BASENAME"

RUN_TS="$(ts_file)"
RUN_LOG="$OUT_DIR/run_${RUN_TS}.log"
RUN_LOG_LATEST="$OUT_DIR/run_latest.log"

TRAJ_PATH="$OUT_DIR/trajectory_${RUN_TS}.json"
TRAJ_LATEST="$OUT_DIR/trajectory_latest.json"

STATUS_PATH="$OUT_DIR/status_${RUN_TS}.json"
STATUS_LATEST="$OUT_DIR/status_latest.json"

DIFF_PATH="$OUT_DIR/git_diff_${RUN_TS}.patch"
DIFF_LATEST="$OUT_DIR/git_diff_latest.patch"

write_status_json () {
  local outcome="$1"; shift || true
  local reason="${1:-}"; shift || true
  {
    echo "{"
    echo "  \"timestamp\": \"$(ts)\","
    echo "  \"phase\": \"openhands\","
    echo "  \"repo_dir\": \"${REPO_DIR}\","
    echo "  \"base_branch\": \"${BASE_BRANCH}\","
    echo "  \"new_branch\": \"${NEW_BRANCH}\","
    echo "  \"run_log\": \"${RUN_LOG}\","
    echo "  \"trajectory\": \"${TRAJ_PATH}\","
    echo "  \"diff\": \"${DIFF_PATH}\","
    echo "  \"outcome\": \"${outcome}\","
    echo "  \"reason\": \"${reason}\""
    if [ -n "${_EXTRA_JSON:-}" ]; then
      echo "  ,${_EXTRA_JSON}"
    fi
    echo "}"
  } > "$STATUS_PATH"
  cp -f "$STATUS_PATH" "$STATUS_LATEST" >/dev/null 2>&1 || true
}

mkdir -p "$OUT_DIR/openhands_store"

WT_ROOT="$REPO_DIR/.atd_worktrees"
WT_PATH="$WT_ROOT/$NEW_BRANCH"
mkdir -p "$WT_ROOT"

# ---- Worktree cleanup helpers (simple + safe) ----
is_under_wt_root () {
  local p="$1"
  local root="$2"
  p="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$p")"
  root="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$root")"
  [[ "$p" == "$root"* ]]
}

cleanup_worktree () {
  # Always try to remove the OpenHands worktree so there is no accidental reuse.
  # Keep the branch intact (we do NOT delete refs/heads/$NEW_BRANCH) so metrics can check it out.
  if [[ -n "${WT_PATH:-}" ]] && [[ -d "$WT_ROOT" ]] && is_under_wt_root "$WT_PATH" "$WT_ROOT"; then
    git -C "$REPO_DIR" worktree remove --force "$WT_PATH" >/dev/null 2>&1 || true
    rm -rf "$WT_PATH" >/dev/null 2>&1 || true
    git -C "$REPO_DIR" worktree prune >/dev/null 2>&1 || true
  fi
}

trap cleanup_worktree EXIT

# Validate base branch exists locally (offline/local-only).
git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/$BASE_BRANCH" || {
  _EXTRA_JSON="\"pushed\": false" write_status_json "config_error" "base_branch_missing_locally"
  exit 10
}

# ---- No-reuse policy: remove any existing worktree dir for this run ----
if [[ -e "$WT_PATH" ]]; then
  echo "Removing existing worktree (no reuse policy): $WT_PATH"
  git -C "$REPO_DIR" worktree remove --force "$WT_PATH" >/dev/null 2>&1 || true
  rm -rf "$WT_PATH" >/dev/null 2>&1 || true
  git -C "$REPO_DIR" worktree prune >/dev/null 2>&1 || true
fi

echo "Creating worktree: $WT_PATH"
if git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/$NEW_BRANCH"; then
  echo "Preparing worktree (checking out '$NEW_BRANCH')"
  git -C "$REPO_DIR" worktree add "$WT_PATH" "$NEW_BRANCH" >/dev/null
else
  echo "Preparing worktree (new branch '$NEW_BRANCH')"
  git -C "$REPO_DIR" worktree add -b "$NEW_BRANCH" "$WT_PATH" "$BASE_BRANCH" >/dev/null
fi

# Ensure worktree is clean before OpenHands.
pushd "$WT_PATH" >/dev/null
git reset --hard -q HEAD
git clean -fdx >/dev/null 2>&1 || true
popd >/dev/null

to_host_path () {
  local p="$1"
  case "$p" in
    /workspace/*) printf "%s/%s" "$HOST_PWD" "${p#/workspace/}" ;;
    /workspace)   printf "%s" "$HOST_PWD" ;;
    *) echo "ERROR: path is not under /workspace: $p" >&2; exit 11 ;;
  esac
}

WT_HOST="$(to_host_path "$WT_PATH")"
OUT_DIR_HOST="$(to_host_path "$OUT_DIR")"
PROMPT_DIR_HOST="$(to_host_path "$PROMPT_DIR")"

GROUP_FLAGS=()
if [ -n "$DOCKER_SOCK_GID" ]; then
  GROUP_FLAGS+=( "--group-add" "$DOCKER_SOCK_GID" )
fi

TTY_FLAGS=""
if [ -t 1 ] && [ -t 0 ]; then
  TTY_FLAGS="-it"
elif [ -t 0 ]; then
  TTY_FLAGS="-i"
fi

NETWORK_FLAGS=()
if [ -n "${ATD_OPENHANDS_NETWORK_CONTAINER:-}" ]; then
  NETWORK_FLAGS+=( "--network" "container:${ATD_OPENHANDS_NETWORK_CONTAINER}" )
fi

_EXTRA_JSON="\"status\":\"started\"" write_status_json "started" ""

echo "Starting OpenHands..."
set -o pipefail
docker run --rm $TTY_FLAGS \
  "${GROUP_FLAGS[@]}" \
  "${NETWORK_FLAGS[@]}" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$WT_HOST:/workspace:rw" \
  -v "$OUT_DIR_HOST:/logs:rw" \
  -v "$PROMPT_DIR_HOST:/prompts:ro" \
  -e FILE_STORE=local \
  -e FILE_STORE_PATH=/logs/openhands_store \
  -e SANDBOX_RUNTIME_CONTAINER_IMAGE="$RUNTIME_IMAGE" \
  -e SANDBOX_USER_ID="$(id -u)" \
  -e SANDBOX_VOLUMES="$WT_HOST:/workspace:rw,$OUT_DIR_HOST:/logs:rw" \
  -e PYTHONPATH="/workspace:${PYTHONPATH:-}" \
  -e LOG_ALL_EVENTS=true \
  -e SAVE_TRAJECTORY_PATH="/logs/trajectory_${RUN_TS}.json" \
  -e LLM_API_KEY="$LLM_API_KEY" \
  -e LLM_BASE_URL="$LLM_BASE_URL_OH" \
  -e LLM_MODEL="$MODEL_FOR_OH" \
  "$OPENHANDS_IMAGE" \
  python -m openhands.core.main \
    -d "/workspace" \
    -f "$PROMPT_IN_CONTAINER" \
    -i "$MAX_ITERS" \
    2>&1 | tee "$RUN_LOG"
RUN_EXIT=$?

cp -f "$RUN_LOG" "$RUN_LOG_LATEST" >/dev/null 2>&1 || true
cp -f "$TRAJ_PATH" "$TRAJ_LATEST" >/dev/null 2>&1 || true

if [ $RUN_EXIT -ne 0 ]; then
  : > "$DIFF_PATH" || true
  cp -f "$DIFF_PATH" "$DIFF_LATEST" >/dev/null 2>&1 || true
  _EXTRA_JSON="\"exit_code\": ${RUN_EXIT}" write_status_json "llm_error" "openhands_exited_nonzero"
  exit 20
fi

# ---- Post-run: commit + diff patch into results ----
pushd "$WT_PATH" >/dev/null

# Ensure git identity exists (local config only).
git config user.name "$GIT_AUTHOR_NAME"
git config user.email "$GIT_AUTHOR_EMAIL"

# If no changes, still write an empty patch file (explicitly) so downstream tooling is stable.
if [ -z "$(git status --porcelain)" ]; then
  : > "$DIFF_PATH"
  cp -f "$DIFF_PATH" "$DIFF_LATEST" >/dev/null 2>&1 || true
  _EXTRA_JSON="\"commit\": null" write_status_json "no_changes" "no_diff_after_llm"
  popd >/dev/null
  exit 0
fi

git add -A

# Commit locally. If commit fails for any reason, we still want a diff patch.
COMMIT_SHA=""
if GIT_AUTHOR_NAME="$GIT_AUTHOR_NAME" \
   GIT_AUTHOR_EMAIL="$GIT_AUTHOR_EMAIL" \
   GIT_COMMITTER_NAME="$GIT_COMMITTER_NAME" \
   GIT_COMMITTER_EMAIL="$GIT_COMMITTER_EMAIL" \
   git commit -m "$COMMIT_MESSAGE" >/dev/null 2>&1; then
  COMMIT_SHA="$(git rev-parse --short HEAD)"
else
  COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || true)"
fi

# Write patch of changes introduced on NEW_BRANCH relative to BASE_BRANCH.
# Use triple-dot so it captures the branch’s changes since merge-base with BASE_BRANCH.
# This avoids the “empty diff” issue when you accidentally diff a merge commit etc.
git diff --binary "$BASE_BRANCH...$NEW_BRANCH" > "$DIFF_PATH" || true
cp -f "$DIFF_PATH" "$DIFF_LATEST" >/dev/null 2>&1 || true

_EXTRA_JSON="\"commit\": \"${COMMIT_SHA:-null}\"" write_status_json "committed" ""
popd >/dev/null

echo "✅ OpenHands done (local)."
echo "  • status:   $STATUS_PATH"
echo "  • latest:   $STATUS_LATEST"
echo "  • log:      $RUN_LOG"
echo "  • traj:     $TRAJ_PATH"
echo "  • diff:     $DIFF_PATH"
echo "  • branch:   $NEW_BRANCH"
echo ""
echo "NOTE: worktree cleanup happens automatically via the EXIT trap."
echo "      The branch is kept locally for metrics; the checkout is removed to prevent reuse."
