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

MAX_ITERS="${MAX_ITERS:-150}"
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

mkdir -p "$LOG_DIR" "$OH_HOME"
RUN_LOG="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
TRAJ_PATH="$LOG_DIR/trajectory.json"

# Helpers
abs() { python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"; }
PROMPT_ABS="$(abs "$PROMPT_PATH")"; LOG_DIR_ABS="$(abs "$LOG_DIR")"; OH_HOME_ABS="$(abs "$OH_HOME")"

WORKBASE="$PWD/.openhands_tmp"
WORKSPACE="$WORKBASE/$(basename "$REPO_SLUG")"
mkdir -p "$WORKBASE" "$LOG_DIR" "$OH_HOME"
trap 'rm -rf "$WORKBASE"' EXIT

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

echo "SANDBOX_VOLUMES: $WORKSPACE:/project:rw,$LOG_DIR:/logs:rw"
test -f "$WORKSPACE/pyproject.toml" && echo "repo looks good" || echo "repo missing?"

# Paths for mounting
PROMPT_DIR="$(dirname "$PROMPT_ABS")"

# Run OpenHands headless (prompt as-is)
set -o pipefail

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

echo "Using OpenHands image : $OPENHANDS_IMAGE"
echo "Using runtime image   : $RUNTIME_IMAGE"

# Mount the repo at /workspace (OpenHands uses this path internally)
# Mount logs at /logs, and mount the prompt's directory read-only so -f is valid
PROMPT_DIR="$(dirname "$PROMPT_ABS")"

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
  echo "OpenHands exited with status $RUN_EXIT — skipping commit/push."
  exit $RUN_EXIT
fi

# Commit & push (outside LLM)
pushd "$WORKSPACE" >/dev/null
if [ -z "$(git status --porcelain)" ]; then
  echo "No changes detected; nothing to commit/push."
else
  git add -A
  git commit -m "$COMMIT_MESSAGE" || true
  echo "Pushing '$NEW_BRANCH' to origin…"
  git push -u origin "$NEW_BRANCH"
fi
popd >/dev/null

echo
echo "Done."
echo "  • log:        $RUN_LOG"
echo "  • trajectory: $TRAJ_PATH"
echo "  • branch:     $NEW_BRANCH"
