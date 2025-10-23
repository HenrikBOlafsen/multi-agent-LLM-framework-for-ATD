#!/usr/bin/env bash
set -euo pipefail

# run_make_rq_tables.sh — iterationless table runner (RQ1, RQ2, RQ3)
#
# Usage:
#   ./run_make_rq_tables.sh \
#     --results-root results \
#     --repos-file repos.txt \
#     --cycles-file cycles_to_analyze.txt \
#     --exp-with expA \
#     --exp-without expA_without_explanation \
#     --outdir analysis_out
#
# Notes:
# - Generates:
#     RQ1: rq1_per_project.csv, rq1_with_vs_without.csv
#     RQ2: rq2_trace.csv
#     RQ3: rq3_by_cycle_size.csv

# Defaults
RESULTS_ROOT="results"
REPOS_FILE="repos.txt"
CYCLES_FILE="cycles_to_analyze.txt"
EXP_WITH="expA"
EXP_WITHOUT="expA_without_explanation"
OUTDIR="analysis_out"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --results-root) RESULTS_ROOT="$2"; shift 2 ;;
    --repos-file) REPOS_FILE="$2"; shift 2 ;;
    --cycles-file) CYCLES_FILE="$2"; shift 2 ;;
    --exp-with) EXP_WITH="$2"; shift 2 ;;
    --exp-without) EXP_WITHOUT="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    -h|--help)
      cat <<EOF
Usage:
  $0 [options]

Options:
  --results-root PATH        (default: results)
  --repos-file PATH          (default: repos.txt)
  --cycles-file PATH         (default: cycles_to_analyze.txt)
  --exp-with NAME            (default: expA)
  --exp-without NAME         (default: expA_without_explanation)
  --outdir PATH              (default: analysis_out)
  -h, --help                 Show this help

Outputs:
  RQ1: rq1_per_project.csv, rq1_with_vs_without.csv
  RQ2: rq2_trace.csv
  RQ3: rq3_by_cycle_size.csv
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
echo "    results-root:   $RESULTS_ROOT"
echo "    repos-file:     $REPOS_FILE"
echo "    cycles-file:    $CYCLES_FILE"
echo "    exp-with:       $EXP_WITH"
echo "    exp-without:    $EXP_WITHOUT"
echo "    outdir:         $OUTDIR"
echo

mkdir -p "$OUTDIR"

# RQ1
echo "[RQ1] Generating rq1_per_project.csv, rq1_with_vs_without.csv ..."
"$PYTHON_BIN" "$SCRIPT_DIR/table_makers/make_rq1_tables.py" \
  --results-root "$RESULTS_ROOT" \
  --repos-file "$REPOS_FILE" \
  --cycles-file "$CYCLES_FILE" \
  --exp-with "$EXP_WITH" \
  --exp-without "$EXP_WITHOUT" \
  --outdir "$OUTDIR"

# RQ2
echo "[RQ2] Generating rq2_trace.csv ..."
"$PYTHON_BIN" "$SCRIPT_DIR/table_makers/make_rq2_tables.py" \
  --results-root "$RESULTS_ROOT" \
  --repos-file "$REPOS_FILE" \
  --cycles-file "$CYCLES_FILE" \
  --exp-with "$EXP_WITH" \
  --exp-without "$EXP_WITHOUT" \
  --outdir "$OUTDIR"

# RQ3
echo "[RQ3] Generating rq3_by_cycle_size.csv ..."
"$PYTHON_BIN" "$SCRIPT_DIR/table_makers/make_rq3_tables.py" \
  --results-root "$RESULTS_ROOT" \
  --repos-file "$REPOS_FILE" \
  --cycles-file "$CYCLES_FILE" \
  --exp-with "$EXP_WITH" \
  --exp-without "$EXP_WITHOUT" \
  --outdir "$OUTDIR"

echo
echo "✅ Done. CSVs written to: $OUTDIR"
