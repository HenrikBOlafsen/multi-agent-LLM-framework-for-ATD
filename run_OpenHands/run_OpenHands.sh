#!/usr/bin/env bash
set -euo pipefail

# Usage (offline/local-only):
#   run_OpenHands.sh <repo_dir> <base_branch> <new_branch> <prompt_path> <out_dir>

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

git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/$BASE_BRANCH" || {
  _EXTRA_JSON="\"pushed\": false" write_status_json "config_error" "base_branch_missing_locally"
  exit 10
}

if [ -d "$WT_PATH/.git" ] || [ -f "$WT_PATH/.git" ]; then
  echo "Reusing existing worktree: $WT_PATH"
else
  echo "Creating worktree: $WT_PATH"
  if git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/$NEW_BRANCH"; then
    git -C "$REPO_DIR" worktree add "$WT_PATH" "$NEW_BRANCH" >/dev/null
  else
    git -C "$REPO_DIR" worktree add -b "$NEW_BRANCH" "$WT_PATH" "$BASE_BRANCH" >/dev/null
  fi
fi

pushd "$WT_PATH" >/dev/null
git reset --hard -q HEAD
git clean -fdx
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

_EXTRA_JSON="\"status\":\"started\"" write_status_json "started" ""

NETWORK_FLAGS=()
if [ -n "${ATD_OPENHANDS_NETWORK_CONTAINER:-}" ]; then
  NETWORK_FLAGS+=( "--network" "container:${ATD_OPENHANDS_NETWORK_CONTAINER}" )
fi

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
  _EXTRA_JSON="\"exit_code\": ${RUN_EXIT}" write_status_json "llm_error" "openhands_exited_nonzero"
  exit 20
fi

pushd "$WT_PATH" >/dev/null
if [ -z "$(git status --porcelain)" ]; then
  _EXTRA_JSON="\"commit\": null" write_status_json "no_changes" "no_diff_after_llm"
  popd >/dev/null
  exit 0
fi

git add -A
if git commit -m "$COMMIT_MESSAGE" >/dev/null 2>&1; then
  COMMIT_SHA="$(git rev-parse --short HEAD)"
else
  COMMIT_SHA="$(git rev-parse --short HEAD || echo null)"
fi

_EXTRA_JSON="\"commit\": \"${COMMIT_SHA}\"" write_status_json "committed" ""
popd >/dev/null

echo "✅ OpenHands done (local)."
echo "  • status:   $STATUS_PATH"
echo "  • latest:   $STATUS_LATEST"
echo "  • log:      $RUN_LOG"
echo "  • traj:     $TRAJ_PATH"
echo "  • branch:   $NEW_BRANCH"
