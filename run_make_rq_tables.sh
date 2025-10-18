#!/usr/bin/env bash
set -euo pipefail

# run_make_rq_tables.sh
# Runs RQ1, RQ2, and RQ3 table generators with consistent arguments.
#
# Usage:
#   ./run_make_rq_tables.sh \
#     --results-root results \
#     --repos-file repos.txt \
#     --exp-with expA \
#     --exp-without expA_without_explanation \
#     --max-iters 5 \
#     --outdir results \
#     --rq2-aggregate final
#
# Notes:
# - Assumes make_rq1_tables.py, make_rq2_tables.py, make_rq3_tables.py
#   are in the same directory as this script.
# - --rq2-aggregate can be "final" or "mean" (passed to RQ2 only).


# Defaults
RESULTS_ROOT="results"
REPOS_FILE="repos.txt"
EXP_WITH="expA"
EXP_WITHOUT="expA_without_explanation"
MAX_ITERS=5
OUTDIR="results"
RQ2_AGGREGATE="final"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --results-root) RESULTS_ROOT="$2"; shift 2 ;;
    --repos-file) REPOS_FILE="$2"; shift 2 ;;
    --exp-with) EXP_WITH="$2"; shift 2 ;;
    --exp-without) EXP_WITHOUT="$2"; shift 2 ;;
    --max-iters) MAX_ITERS="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --rq2-aggregate) RQ2_AGGREGATE="$2"; shift 2 ;;
    -h|--help)
      cat <<EOF
Usage:
  $0 [options]

Options:
  --results-root PATH          (default: results)
  --repos-file PATH            (default: repos.txt)
  --exp-with NAME              (default: expA)
  --exp-without NAME           (default: expA_without_explanation)
  --max-iters N                (default: 5)
  --outdir PATH                (default: results)
  --rq2-aggregate final|mean   (default: final)
  -h, --help                   Show this help

Examples:
  $0 --results-root results --repos-file repos.txt --max-iters 5 --outdir results
  $0 --rq2-aggregate mean
EOF
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1 ;;
  esac
done

# Resolve script dir and python
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> Running table generation"
echo "    results-root:        $RESULTS_ROOT"
echo "    repos-file:          $REPOS_FILE"
echo "    exp-with:            $EXP_WITH"
echo "    exp-without:         $EXP_WITHOUT"
echo "    max-iters:           $MAX_ITERS"
echo "    outdir:              $OUTDIR"
echo "    rq2-aggregate:       $RQ2_AGGREGATE"
echo

mkdir -p "$OUTDIR"

# RQ1
echo "[RQ1] Generating rq1_per_target.csv, rq1_overview.csv, rq1_per_project.csv ..."
"$PYTHON_BIN" "$SCRIPT_DIR/make_rq1_tables.py" \
  --results-root "$RESULTS_ROOT" \
  --repos-file "$REPOS_FILE" \
  --exp-with "$EXP_WITH" \
  --exp-without "$EXP_WITHOUT" \
  --max-iters "$MAX_ITERS" \
  --outdir "$OUTDIR"

# RQ2
echo "[RQ2] Generating rq2_trace.csv, rq2A_final.csv, rq2B_delta.csv ..."
"$PYTHON_BIN" "$SCRIPT_DIR/make_rq2_tables.py" \
  --results-root "$RESULTS_ROOT" \
  --repos-file "$REPOS_FILE" \
  --exp-with "$EXP_WITH" \
  --exp-without "$EXP_WITHOUT" \
  --max-iters "$MAX_ITERS" \
  --aggregate "$RQ2_AGGREGATE" \
  --outdir "$OUTDIR"

# RQ3
echo "[RQ3] Generating rq3_progress.csv, rq3_bins.csv, rq3_corr.csv ..."
"$PYTHON_BIN" "$SCRIPT_DIR/make_rq3_tables.py" \
  --results-root "$RESULTS_ROOT" \
  --repos-file "$REPOS_FILE" \
  --exp-with "$EXP_WITH" \
  --exp-without "$EXP_WITHOUT" \
  --max-iters "$MAX_ITERS" \
  --outdir "$OUTDIR"

echo
echo "✅ Done. CSVs written to: $OUTDIR"