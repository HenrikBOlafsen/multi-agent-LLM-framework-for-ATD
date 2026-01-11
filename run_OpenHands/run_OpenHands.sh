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
OH_HOME="${OH_HOME:-$HOME/.openhands}"
# --------------------------------------------------------

usage() { echo "usage: $0 <owner/repo> <base_branch> <new_branch> <prompt_path>"; exit 1; }
[ $# -eq 4 ] || usage

REPO_SLUG="$1"; BASE_BRANCH="$2"; NEW_BRANCH="$3"; PROMPT_PATH="$4"

[[ "$REPO_SLUG" =~ ^[^/]+/[^/]+$ ]] || { echo "Invalid slug: $REPO_SLUG (expected owner/repo)"; exit 2; }
[ -n "$GITHUB_TOKEN" ] || { echo "GITHUB_TOKEN is required"; exit 3; }
[ -f "$PROMPT_PATH" ] || { echo "Prompt not found: $PROMPT_PATH"; exit 4; }
[ -n "$LLM_API_KEY" ] || { echo "LLM_API_KEY is required"; exit 5; }

# ---- helpers ----
abs() { python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"; }

# Use ABSOLUTE paths for all logs/status to avoid CWD issues
LOG_DIR_ABS="$(abs "$LOG_DIR")"
OH_HOME_ABS="$(abs "$OH_HOME")"
PROMPT_ABS="$(abs "$PROMPT_PATH")"
mkdir -p "$LOG_DIR_ABS" "$OH_HOME_ABS"

RUN_LOG="$LOG_DIR_ABS/run_$(date +%Y%m%d_%H%M%S).log"
TRAJ_PATH="$LOG_DIR_ABS/trajectory.json"
STATUS_PATH="$LOG_DIR_ABS/status.json"

ts() { date -Iseconds; }

write_status_json () {
  # $1 outcome, $2 reason, optional extra k:v pairs via env var _EXTRA_JSON (raw JSON attrs)
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

# ---- fail-safe finalizer (ensures we never leave 'started' hanging) ----
__OH_FINALIZED=0
WORKSPACE=""
finalize_and_cleanup () {
  # Always try to finalize if no terminal status was written
  if [ "$__OH_FINALIZED" -eq 0 ]; then
    REASON="wrapper_did_not_finalize"
    if [ -f "$TRAJ_PATH" ]; then
      REASON="incomplete_status_but_trajectory_present"
    fi
    _EXTRA_JSON="\"pushed\": false" write_status_json "incomplete_status" "$REASON"
  fi
  # Cleanup workspace if set
  if [ -n "$WORKSPACE" ] && [ -d "$WORKSPACE" ]; then
    rm -rf "$WORKSPACE" || true
  fi
}
trap finalize_and_cleanup EXIT

# Mark start
_EXTRA_JSON="\"status\":\"started\"" write_status_json "started" ""

# --- robust, unique workspace per run ---
WORKBASE="$PWD/.openhands_tmp"
mkdir -p "$WORKBASE"
WORKSPACE="$WORKBASE/$(basename "$REPO_SLUG")_$(date +%s%N)"
[ -d "$WORKSPACE" ] && rm -rf "$WORKSPACE"
mkdir -p "$WORKSPACE"

GIT_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO_SLUG}.git"

echo "Cloning $REPO_SLUG → $WORKSPACE"
git clone "$GIT_URL" "$WORKSPACE"

pushd "$WORKSPACE" >/dev/null
# Set git identity only if provided
[ -n "${GIT_USER_NAME:-}" ]  && git config user.name  "$GIT_USER_NAME"
[ -n "${GIT_USER_EMAIL:-}" ] && git config user.email "$GIT_USER_EMAIL"

# Branch prep (outside LLM)
git fetch origin --quiet || true
if git rev-parse --verify --quiet "origin/$BASE_BRANCH"; then
  git switch -C "$BASE_BRANCH" "origin/$BASE_BRANCH"
else
  git switch -C "$BASE_BRANCH"
fi
git switch -C "$NEW_BRANCH"
popd >/dev/null

echo "Running OpenHands (slug mode)…"
echo "  repo:    $REPO_SLUG"
echo "  base:    $BASE_BRANCH"
echo "  new:     $NEW_BRANCH"
echo "  prompt:  $PROMPT_ABS"
echo "Logs: $RUN_LOG"
echo "Trajectory: $TRAJ_PATH"

# TTY flags: avoid '-t' when piping to tee
TTY_FLAGS=""
if [ -t 1 ] && [ -t 0 ]; then
  TTY_FLAGS="-it"
elif [ -t 0 ]; then
  TTY_FLAGS="-i"
fi

# Harden image defaults even if env exports empty strings
: "${OPENHANDS_IMAGE:=docker.all-hands.dev/all-hands-ai/openhands:0.59}"
: "${RUNTIME_IMAGE:=docker.all-hands.dev/all-hands-ai/runtime:0.59-nikolaik}"

# Paths for mounting
PROMPT_DIR="$(dirname "$PROMPT_ABS")"

# Run OpenHands headless (prompt as-is)
set -o pipefail
docker run --rm $TTY_FLAGS \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$WORKSPACE:/workspace:rw" \
  -v "$LOG_DIR_ABS:/logs:rw" \
  -v "$PROMPT_DIR:$PROMPT_DIR:ro" \
  $( [ -n "${DOCKER_HOST:-}" ] && printf -- '-e DOCKER_HOST=%s ' "$DOCKER_HOST" || true ) \
  -e SANDBOX_RUNTIME_CONTAINER_IMAGE="$RUNTIME_IMAGE" \
  -e SANDBOX_USER_ID="$(id -u)" \
  -e SANDBOX_VOLUMES="$WORKSPACE:/workspace:rw,$LOG_DIR_ABS:/logs:rw" \
  -e PYTHONPATH="/workspace:${PYTHONPATH:-}" \
  -e LLM_MODEL="$LLM_MODEL" \
  -e LLM_BASE_URL="$LLM_BASE_URL" \
  -e LLM_API_KEY="$LLM_API_KEY" \
  -e LOG_ALL_EVENTS=true \
  -e SAVE_TRAJECTORY_PATH="/logs/trajectory.json" \
  "$OPENHANDS_IMAGE" \
  python -m openhands.core.main \
    -d "/workspace" \
    -f "$PROMPT_ABS" \
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
    # Classify common push errors (best-effort)
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
