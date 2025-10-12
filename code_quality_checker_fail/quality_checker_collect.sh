#!/usr/bin/env bash
# Usage:
#   ./quality_checker_collect.sh <REPO_PATH> <LABEL> <SRC_PATH> [<SRC_PATH> ...]

set -eo pipefail
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TZ=UTC
export PYTHONHASHSEED=0

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <REPO_PATH> <LABEL> <SRC_PATH> [<SRC_PATH> ...]" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=quality_checker_lib.sh
source "$HERE/quality_checker_lib.sh"
set -u

REPO_PATH="$(realpath "$1")"; shift
LABEL="$1"; shift
mapfile -t SRC_PATHS < <(printf '%s\n' "$@")

git -C "$REPO_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "Error: $REPO_PATH is not a git repository." >&2; exit 1; }

REPO_NAME="$(basename "$REPO_PATH")"
OUT_ROOT="${OUT_ROOT:-.quality}"
OUT_DIR="$OUT_ROOT/$REPO_NAME/$LABEL"
mkdir -p "$OUT_DIR"
OUT_ABS="$(realpath "$OUT_DIR")"

quality_checker_prepare_worktree "$REPO_PATH" "$LABEL"

[[ ${#SRC_PATHS[@]} -ge 1 ]] || { echo "Error: you must specify at least one SRC_PATH." >&2; exit 2; }
for p in "${SRC_PATHS[@]}"; do
  [[ -d "$WT_ROOT/$p" ]] || { echo "Error: source path '$p' not found in worktree: $WT_ROOT" >&2; exit 1; }
done

quality_checker_write_metadata "$WT_ROOT" "$OUT_ABS" "${SRC_PATHS[@]}"

echo "==> [${REPO_NAME}] analyzing ref: $LABEL"
echo "Repository: $REPO_PATH"
echo "Worktree:   $WT_ROOT"
echo -n "Sources:    "; printf '%s ' "${SRC_PATHS[@]}"; echo
echo "Output:     $OUT_ABS"

ISOLATE_TEST_ENV="${ISOLATE_TEST_ENV:-1}"
QUALITY_PER_REF_VENV="${QUALITY_PER_REF_VENV:-0}"          # 0=shared per repo (default), 1=per label
QUALITY_VENV_ARGS="${QUALITY_VENV_ARGS:---system-site-packages}"

# Prefer the uv-managed base interpreter when available
if [[ -x "/opt/app/.venv/bin/python" ]]; then
  BASE_PYTHON_DEFAULT="/opt/app/.venv/bin/python"
else
  BASE_PYTHON_DEFAULT="python"
fi
BASE_PYTHON="${BASE_PYTHON:-$BASE_PYTHON_DEFAULT}"

if [[ "$ISOLATE_TEST_ENV" == "1" ]]; then
  if [[ "$QUALITY_PER_REF_VENV" == "1" ]]; then
    VENV_DIR="$OUT_ABS/.venv"
  else
    VENV_DIR="$OUT_ROOT/$REPO_NAME/.venv"
  fi

  # Ensure directory exists and resolve an ABSOLUTE path for the venv
  mkdir -p "$VENV_DIR"
  VENV_DIR_ABS="$(realpath "$VENV_DIR")"

  if [[ ! -x "$VENV_DIR_ABS/bin/python" ]]; then
    echo "==> Creating venv: $VENV_DIR_ABS (base: $BASE_PYTHON $QUALITY_VENV_ARGS)"
    if [[ -n "$QUALITY_VENV_ARGS" ]]; then
      "$BASE_PYTHON" -m venv $QUALITY_VENV_ARGS "$VENV_DIR_DIR_IGNORE" >/dev/null 2>&1 || true
      # Above line was defensive; create for real below (avoids shellcheck complaints on $QUALITY_VENV_ARGS)
      "$BASE_PYTHON" -m venv $QUALITY_VENV_ARGS "$VENV_DIR_ABS"
    else
      "$BASE_PYTHON" -m venv "$VENV_DIR_ABS"
    fi
    "$VENV_DIR_ABS/bin/python" -m pip install -U pip >/dev/null
  else
    echo "==> Reusing venv:  $VENV_DIR_ABS"
  fi

  VENV_PY="$VENV_DIR_ABS/bin/python"

  # Prepare environment: reuse global tools if available; install project deps + any missing tools
  "$HERE/quality_checker_prepare_env.sh" "$WT_ROOT" --python "$VENV_PY"

  # Record interpreter path for downstream script (ABSOLUTE!)
  echo "$VENV_PY" > "$OUT_ABS/pytest_python.txt"
  "$VENV_PY" -V > "$OUT_ABS/python_version.txt"
fi

exec "$HERE/quality_checker_run_tools.sh" "$WT_ROOT" "$OUT_ABS"
