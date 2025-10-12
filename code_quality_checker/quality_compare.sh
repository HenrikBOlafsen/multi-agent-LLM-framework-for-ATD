#!/usr/bin/env bash
# Usage:
#   ./quality_compare.sh <REPO_PATH> <BASELINE_REF> <POST_REF> [SRC_HINT] [OUT_JSON]
#
# Notes:
# - Calls ./quality_collect.sh twice (once per ref). Each call uses its own
#   temporary git worktree, so the main working tree stays clean.
# - Then calls quality_summarize.py to produce one unified JSON with deltas.
# - Respects OUT_ROOT if you’ve set it (defaults to .quality).

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <REPO_PATH> <BASELINE_REF> <POST_REF> [SRC_HINT] [OUT_JSON]" >&2
  exit 2
fi

REPO_PATH="$(realpath "$1")"
BASELINE="$2"
POST="$3"
SRC_HINT="${4:-}"
REPO_NAME="$(basename "$REPO_PATH")"

OUT_ROOT="${OUT_ROOT:-.quality}"
DEFAULT_JSON="${REPO_NAME}_${BASELINE}_vs_${POST}.json"
OUT_JSON="${5:-$DEFAULT_JSON}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECT="$SCRIPT_DIR/quality_collect.sh"
SUMMARIZE="$SCRIPT_DIR/quality_summarize.py"

if [[ ! -x "$COLLECT" ]]; then
  echo "Missing or non-executable: $COLLECT" >&2
  exit 1
fi
if ! python -c "import sys" >/dev/null 2>&1; then
  echo "Python not found in PATH" >&2
  exit 1
fi
if [[ ! -f "$SUMMARIZE" ]]; then
  echo "Missing: $SUMMARIZE" >&2
  exit 1
fi

echo "==> Collecting on baseline: $BASELINE"
"$COLLECT" "$REPO_PATH" "$BASELINE" "$SRC_HINT"

echo "==> Collecting on post:     $POST"
"$COLLECT" "$REPO_PATH" "$POST" "$SRC_HINT"

echo "==> Summarizing → $OUT_JSON"
python "$SUMMARIZE" "$OUT_ROOT" "$REPO_NAME" "$BASELINE" "$POST" "$OUT_JSON"

echo "Done. Unified report: $OUT_JSON"
