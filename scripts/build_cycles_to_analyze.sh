#!/usr/bin/env bash
set -euo pipefail

# Usage (ALL ARGS REQUIRED):
#   scripts/build_cycles_to_analyze.sh \
#     --repos-file repos_dev.txt \
#     --results-root results \
#     --size-bins "2-3,4-6,7-8" \
#     --total 50 \
#     --out cycles_to_analyze_dev.txt \
#     --max-per-repo 8

REPOS_FILE=""
RESULTS_ROOT=""
SIZE_BINS=""
TOTAL=""
OUT_PATH=""
MAX_PER_REPO=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repos-file) REPOS_FILE="$2"; shift 2 ;;
    --results-root) RESULTS_ROOT="$2"; shift 2 ;;
    --size-bins) SIZE_BINS="$2"; shift 2 ;;
    --total) TOTAL="$2"; shift 2 ;;
    --out) OUT_PATH="$2"; shift 2 ;;
    --max-per-repo) MAX_PER_REPO="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,80p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$REPOS_FILE" ]] || { echo "ERROR: --repos-file is required" >&2; exit 2; }
[[ -n "$RESULTS_ROOT" ]] || { echo "ERROR: --results-root is required" >&2; exit 2; }
[[ -n "$SIZE_BINS" ]] || { echo "ERROR: --size-bins is required" >&2; exit 2; }
[[ -n "$TOTAL" ]] || { echo "ERROR: --total is required" >&2; exit 2; }
[[ -n "$OUT_PATH" ]] || { echo "ERROR: --out is required" >&2; exit 2; }
[[ -n "$MAX_PER_REPO" ]] || { echo "ERROR: --max-per-repo is required" >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 "$ROOT/ATD_identification/build_cycles_to_analyze.py" \
  --repos-file "$REPOS_FILE" \
  --results-root "$RESULTS_ROOT" \
  --size-bins "$SIZE_BINS" \
  --total "$TOTAL" \
  --out "$OUT_PATH" \
  --max-per-repo "$MAX_PER_REPO"

echo "✅ Wrote: $OUT_PATH"