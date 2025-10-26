#!/usr/bin/env bash
set -euo pipefail

# New simple interface:
#   ./run_make_rq_tables.sh \
#     --results-roots resultsA resultsB resultsC \
#     --exp-ids       expA     expB     expC     \
#     --repos-file repos.txt \
#     --cycles-file cycles_to_analyze.txt \
#     --outdir analysis_out
#
# WITHOUT is derived as "<EXP>_without_explanation" for each item.

RESULTS_ROOTS=""
EXP_IDS=""
REPOS_FILE="repos.txt"
CYCLES_FILE="cycles_to_analyze.txt"
OUTDIR="analysis_out"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --results-roots) shift; while [[ $# -gt 0 && "${1:0:2}" != "--" ]]; do RESULTS_ROOTS+="${1} "; shift; done ;;
    --exp-ids) shift; while [[ $# -gt 0 && "${1:0:2}" != "--" ]]; do EXP_IDS+="${1} "; shift; done ;;
    --repos-file) REPOS_FILE="$2"; shift 2 ;;
    --cycles-file) CYCLES_FILE="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    -h|--help)
      cat <<EOF
Usage:
  $0 --results-roots <ROOT...> --exp-ids <EXP...> --repos-file repos.txt --cycles-file cycles_to_analyze.txt --outdir out
Notes:
  - Roots and EXP IDs must be the same length and are paired by position.
  - WITHOUT is derived as "<EXP>_without_explanation".
EOF
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$RESULTS_ROOTS" || -z "$EXP_IDS" ]]; then
  echo "ERROR: require --results-roots and --exp-ids" >&2; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Compose common flags
# shellcheck disable=SC2206
ROOTS_ARR=( $RESULTS_ROOTS )
EXP_ARR=( $EXP_IDS )
RQ_FLAGS=( --results-roots "${ROOTS_ARR[@]}" --exp-ids "${EXP_ARR[@]}" --repos-file "$REPOS_FILE" --cycles-file "$CYCLES_FILE" --outdir "$OUTDIR" )

echo "==> RQ tables"
echo "    roots:      ${ROOTS_ARR[*]}"
echo "    exp-ids:    ${EXP_ARR[*]}"
echo "    repos:      $REPOS_FILE"
echo "    cycles:     $CYCLES_FILE"
echo "    outdir:     $OUTDIR"
echo

echo "[RQ1]"
"$PYTHON_BIN" "$SCRIPT_DIR/table_makers/make_rq1_tables.py" "${RQ_FLAGS[@]}"

echo "[RQ2]"
"$PYTHON_BIN" "$SCRIPT_DIR/table_makers/make_rq2_tables.py" "${RQ_FLAGS[@]}"

echo "[RQ3]"
"$PYTHON_BIN" "$SCRIPT_DIR/table_makers/make_rq3_tables.py" "${RQ_FLAGS[@]}"

echo
echo "✅ Done. CSVs written to: $OUTDIR"
