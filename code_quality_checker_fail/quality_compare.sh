#!/usr/bin/env bash
# Usage:
#   ./quality_compare.sh <REPO_PATH> <BASELINE_REF> <POST_REF> <SRC_PATH> [<SRC_PATH> ...] [--out <OUT_JSON>]
#
# Behavior:
# - Requires git repo and explicit source paths.
# - Collects metrics for BASELINE and POST (each in its own worktree).
# - Summarizes into a single JSON and validates it.

set -euo pipefail

export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TZ=UTC
export PYTHONHASHSEED=0

if [[ $# -lt 4 ]]; then
  echo "Usage: $0 <REPO_PATH> <BASELINE_REF> <POST_REF> <SRC_PATH> [<SRC_PATH> ...] [--out <OUT_JSON>]" >&2
  exit 2
fi

REPO_PATH="$(realpath "$1")"; shift
BASELINE="$1"; shift
POST="$1"; shift

OUT_JSON=""
SRC_PATHS=()
while (( "$#" )); do
  case "${1:-}" in
    --out) shift; OUT_JSON="${1:-}"; [[ -z "$OUT_JSON" ]] && { echo "Missing value after --out" >&2; exit 2; }; shift ;;
    *) SRC_PATHS+=("$1"); shift ;;
  esac
done
[[ ${#SRC_PATHS[@]} -ge 1 ]] || { echo "Error: at least one SRC_PATH required." >&2; exit 2; }

if ! git -C "$REPO_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: $REPO_PATH is not a git repository." >&2
  exit 1
fi
python -c "import sys" >/dev/null 2>&1 || { echo "Error: Python not found in PATH." >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECT="$HERE/quality_checker_collect.sh"
SUMMARIZE="$HERE/quality_summarize.py"

[[ -x "$COLLECT" ]]   || { echo "Error: Missing or non-executable: $COLLECT" >&2; exit 1; }
[[ -f "$SUMMARIZE" ]] || { echo "Error: Missing summarizer: $SUMMARIZE" >&2; exit 1; }

REPO_NAME="$(basename "$REPO_PATH")"
OUT_ROOT="${OUT_ROOT:-.quality}"
DEFAULT_JSON="${REPO_NAME}_${BASELINE}_vs_${POST}.json"
OUT_JSON="${OUT_JSON:-$DEFAULT_JSON}"

echo "==> Collecting on baseline: $BASELINE"
"$COLLECT" "$REPO_PATH" "$BASELINE" "${SRC_PATHS[@]}"

echo "==> Collecting on post:     $POST"
"$COLLECT" "$REPO_PATH" "$POST" "${SRC_PATHS[@]}"

echo "==> Summarizing → $OUT_JSON"
python "$SUMMARIZE" "$OUT_ROOT" "$REPO_NAME" "$BASELINE" "$POST" "$OUT_JSON"

[[ -s "$OUT_JSON" ]] || { echo "Error: summarizer did not produce $OUT_JSON" >&2; exit 1; }
python - <<'PY' "$OUT_JSON"
import json, sys, pathlib
p=pathlib.Path(sys.argv[1])
json.loads(p.read_text(encoding="utf-8"))
PY

echo "Done. Unified report: $OUT_JSON"
