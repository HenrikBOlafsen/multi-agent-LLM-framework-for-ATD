#!/usr/bin/env bash
set -euo pipefail

# Load .env next to this script if present (and export its vars)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/../.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

# --------- config (env wins; .env fills blanks) ---------
LLM_MODEL="${LLM_MODEL:-}"
LLM_BASE_URL="${LLM_BASE_URL:-}"
LLM_API_KEY="${LLM_API_KEY:-}"

GITHUB_TOKEN="${GITHUB_TOKEN:-}"
OPENHANDS_IMAGE="${OPENHANDS_IMAGE:-docker.all-hands.dev/all-hands-ai/openhands:0.59}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-docker.all-hands.dev/all-hands-ai/runtime:0.59-nikolaik}"

MAX_ITERS="${MAX_ITERS:-100}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-Refactor: break dependency cycle}"
GIT_USER_NAME="${GIT_USER_NAME:-}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-}"

LOG_DIR="${LOG_DIR:-$PWD/openhands_logs}"
# --------------------------------------------------------

usage() { echo "usage: $0 <owner/repo> <base_branch> <new_branch> <prompt_path>"; exit 1; }
[ $# -eq 4 ] || usage

REPO_SLUG="$1"; BASE_BRANCH="$2"; NEW_BRANCH="$3"; PROMPT_PATH="$4"

[[ "$REPO_SLUG" =~ ^[^/]+/[^/]+$ ]] || { echo "Invalid slug: $REPO_SLUG (expected owner/repo)"; exit 2; }
[ -n "$GITHUB_TOKEN" ] || { echo "GITHUB_TOKEN is required"; exit 3; }
[ -f "$PROMPT_PATH" ] || { echo "Prompt not found: $PROMPT_PATH"; exit 4; }
[ -n "$LLM_API_KEY" ] || { echo "LLM_API_KEY is required"; exit 5; }
[ -n "$LLM_BASE_URL" ] || { echo "LLM_BASE_URL is required"; exit 6; }
[ -n "$LLM_MODEL" ] || { echo "LLM_MODEL is required"; exit 7; }

abs() { python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"; }
ts() { date -Iseconds; }

# IMPORTANT: For Docker-outside-Docker bind mounts we need HOST paths, not /workspace paths.
# Provide HOST_PWD when starting dev container:  -e HOST_PWD="$(pwd)"
HOST_PWD="${HOST_PWD:-}"
if [ -z "$HOST_PWD" ]; then
  echo "ERROR: HOST_PWD is not set."
  echo "Start the dev container with:  -e HOST_PWD=\"\$(pwd)\""
  exit 9
fi
HOST_PWD="${HOST_PWD%/}"

# docker.sock group id (so OpenHands container can access docker.sock)
DOCKER_SOCK_GID=""
if [ -S /var/run/docker.sock ]; then
  DOCKER_SOCK_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || true)"
fi

# Normalize base URL to .../v1 for OpenAI-compatible servers
LLM_BASE_URL="${LLM_BASE_URL%/}"
if [[ "$LLM_BASE_URL" != */v1 ]]; then
  LLM_BASE_URL="${LLM_BASE_URL}/v1"
fi

# ---- CRITICAL: build the model string LiteLLM expects ----
# If your model id is a filesystem path, prefix it with "openai/" for LiteLLM routing.
MODEL_FOR_OH="$LLM_MODEL"
if [[ "$MODEL_FOR_OH" == /* ]]; then
  MODEL_FOR_OH="openai/${MODEL_FOR_OH}"
elif [[ "$MODEL_FOR_OH" != openai/* ]]; then
  # If you ever switch to a normal model name, you can still force openai provider
  MODEL_FOR_OH="openai/${MODEL_FOR_OH}"
fi

# Paths INSIDE dev container (used for local file operations)
LOG_DIR_ABS="$(abs "$LOG_DIR")"
PROMPT_ABS="$(abs "$PROMPT_PATH")"
mkdir -p "$LOG_DIR_ABS"

RUN_LOG="$LOG_DIR_ABS/run_$(date +%Y%m%d_%H%M%S).log"
TRAJ_PATH="$LOG_DIR_ABS/trajectory.json"
STATUS_PATH="$LOG_DIR_ABS/status.json"

write_status_json () {
  local outcome="$1"; shift || true
  local reason="${1:-}"; shift || true
  mkdir -p "$(dirname "$STATUS_PATH")"
  {
    echo "{"
    echo "  \"timestamp\": \"$(ts)\","
    echo "  \"phase\": \"openhands\","
    echo "  \"repo\": \"${REPO_SLUG}\","
    echo "  \"base_branch\": \"${BASE_BRANCH}\","
    echo "  \"new_branch\": \"${NEW_BRANCH}\","
    echo "  \"run_log\": \"${RUN_LOG}\","
    echo "  \"trajectory\": \"${TRAJ_PATH}\","
    echo "  \"outcome\": \"${outcome}\","
    echo "  \"reason\": \"${reason}\""
    if [ -n "${_EXTRA_JSON:-}" ]; then
      echo "  ,${_EXTRA_JSON}"
    fi
    echo "}"
  } > "$STATUS_PATH"
}

__OH_FINALIZED=0
WORKSPACE=""
finalize_and_cleanup () {
  if [ "$__OH_FINALIZED" -eq 0 ]; then
    local REASON="wrapper_did_not_finalize"
    if [ -f "$TRAJ_PATH" ]; then
      REASON="incomplete_status_but_trajectory_present"
    fi
    _EXTRA_JSON="\"pushed\": false" write_status_json "incomplete_status" "$REASON"
  fi
  if [ -n "$WORKSPACE" ] && [ -d "$WORKSPACE" ]; then
    rm -rf "$WORKSPACE" || true
  fi
}
trap finalize_and_cleanup EXIT

_EXTRA_JSON="\"status\":\"started\"" write_status_json "started" ""

# Workspace for cloning (inside dev container)
WORKBASE="$PWD/.openhands_tmp"
mkdir -p "$WORKBASE"
WORKSPACE="$WORKBASE/$(basename "$REPO_SLUG")_$(date +%s%N)"
rm -rf "$WORKSPACE" || true
mkdir -p "$WORKSPACE"

GIT_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO_SLUG}.git"
echo "Cloning $REPO_SLUG → $WORKSPACE"
git clone "$GIT_URL" "$WORKSPACE"

pushd "$WORKSPACE" >/dev/null
[ -n "${GIT_USER_NAME:-}" ]  && git config user.name  "$GIT_USER_NAME"
[ -n "${GIT_USER_EMAIL:-}" ] && git config user.email "$GIT_USER_EMAIL"

git fetch origin --quiet || true
if git rev-parse --verify --quiet "origin/$BASE_BRANCH"; then
  git switch -C "$BASE_BRANCH" "origin/$BASE_BRANCH"
else
  git switch -C "$BASE_BRANCH"
fi
git switch -C "$NEW_BRANCH"
popd >/dev/null

echo "Running OpenHands (slug mode)…"
echo "  repo:          $REPO_SLUG"
echo "  base:          $BASE_BRANCH"
echo "  new:           $NEW_BRANCH"
echo "  prompt:        $PROMPT_ABS"
echo "  logs:          $RUN_LOG"
echo "  trajectory:    $TRAJ_PATH"
echo "  LLM_BASE_URL:  $LLM_BASE_URL"
echo "  LLM_MODEL:     $LLM_MODEL"
echo "  OH_MODEL:      $MODEL_FOR_OH"

# TTY flags
TTY_FLAGS=""
if [ -t 1 ] && [ -t 0 ]; then
  TTY_FLAGS="-it"
elif [ -t 0 ]; then
  TTY_FLAGS="-i"
fi

: "${OPENHANDS_IMAGE:=docker.all-hands.dev/all-hands-ai/openhands:0.59}"
: "${RUNTIME_IMAGE:=docker.all-hands.dev/all-hands-ai/runtime:0.59-nikolaik}"

PROMPT_DIR="$(dirname "$PROMPT_ABS")"

# Translate dev-container paths (/workspace/...) to host paths ($HOST_PWD/...)
to_host_path () {
  local p="$1"
  case "$p" in
    /workspace/*) printf "%s/%s" "$HOST_PWD" "${p#/workspace/}" ;;
    /workspace)   printf "%s" "$HOST_PWD" ;;
    *)
      echo "ERROR: path is not under /workspace: $p" >&2
      exit 11
      ;;
  esac
}

WORKSPACE_HOST="$(to_host_path "$WORKSPACE")"
LOG_DIR_HOST="$(to_host_path "$LOG_DIR_ABS")"
PROMPT_DIR_HOST="$(to_host_path "$PROMPT_DIR")"

# File store (avoid /.openhands permission issues)
mkdir -p "$LOG_DIR_ABS/openhands_store"

GROUP_FLAGS=()
if [ -n "$DOCKER_SOCK_GID" ]; then
  GROUP_FLAGS+=( "--group-add" "$DOCKER_SOCK_GID" )
fi

# --- prompt mount: stable inside container ---
PROMPT_BASENAME="$(basename "$PROMPT_ABS")"
PROMPT_IN_CONTAINER="/prompts/$PROMPT_BASENAME"

set -o pipefail
docker run --rm $TTY_FLAGS \
  "${GROUP_FLAGS[@]}" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$WORKSPACE_HOST:/workspace:rw" \
  -v "$LOG_DIR_HOST:/logs:rw" \
  -v "$PROMPT_DIR_HOST:/prompts:ro" \
  $( [ -n "${DOCKER_HOST:-}" ] && printf -- '-e DOCKER_HOST=%s ' "$DOCKER_HOST" || true ) \
  -e FILE_STORE=local \
  -e FILE_STORE_PATH=/logs/openhands_store \
  -e SANDBOX_RUNTIME_CONTAINER_IMAGE="$RUNTIME_IMAGE" \
  -e SANDBOX_USER_ID="$(id -u)" \
  -e SANDBOX_VOLUMES="$WORKSPACE_HOST:/workspace:rw,$LOG_DIR_HOST:/logs:rw" \
  -e PYTHONPATH="/workspace:${PYTHONPATH:-}" \
  -e LOG_ALL_EVENTS=true \
  -e SAVE_TRAJECTORY_PATH="/logs/trajectory.json" \
  -e LLM_API_KEY="$LLM_API_KEY" \
  -e LLM_BASE_URL="$LLM_BASE_URL" \
  -e LLM_MODEL="$MODEL_FOR_OH" \
  "$OPENHANDS_IMAGE" \
  python -m openhands.core.main \
    -d "/workspace" \
    -f "$PROMPT_IN_CONTAINER" \
    -i "$MAX_ITERS" \
    2>&1 | tee "$RUN_LOG"
RUN_EXIT=$?

if [ $RUN_EXIT -ne 0 ]; then
  _EXTRA_JSON="\"exit_code\": ${RUN_EXIT}" write_status_json "llm_error" "openhands_exited_nonzero"
  __OH_FINALIZED=1
  echo "OpenHands exited with status $RUN_EXIT — skipping commit/push."
  exit 10
fi

# Commit & push (outside LLM)
pushd "$WORKSPACE" >/dev/null
if [ -z "$(git status --porcelain)" ]; then
  _EXTRA_JSON="\"commit\": null, \"pushed\": false" write_status_json "no_changes" "no_diff_after_llm"
  __OH_FINALIZED=1
  echo "No changes detected; nothing to commit/push."
else
  git add -A
  if git commit -m "$COMMIT_MESSAGE" >/dev/null 2>&1; then
    COMMIT_SHA="$(git rev-parse --short HEAD)"
  else
    COMMIT_SHA="$(git rev-parse --short HEAD || echo null)"
  fi
  echo "Pushing '$NEW_BRANCH' to origin…"
  if git push -u origin "$NEW_BRANCH"; then
    _EXTRA_JSON="\"commit\": \"${COMMIT_SHA}\", \"pushed\": true" write_status_json "pushed" ""
    __OH_FINALIZED=1
  else
    PUSH_REASON="push_failed"
    if git ls-remote --exit-code --heads "https://github.com/${REPO_SLUG}.git" "$NEW_BRANCH" >/dev/null 2>&1; then
      PUSH_REASON="non_fast_forward_or_protected"
    fi
    _EXTRA_JSON="\"commit\": \"${COMMIT_SHA}\", \"pushed\": false" write_status_json "push_failed" "$PUSH_REASON"
    __OH_FINALIZED=1
    echo "Push failed."
    popd >/dev/null
    exit 20
  fi
fi
popd >/dev/null

echo
echo "Done."
echo "  • log:        $RUN_LOG"
echo "  • trajectory: $TRAJ_PATH"
echo "  • branch:     $NEW_BRANCH"
