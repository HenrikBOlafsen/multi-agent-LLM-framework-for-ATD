#!/usr/bin/env bash
set -euo pipefail

CONFIG=""
OUTDIR="analysis_out"
EXPERIMENT_IDS=""
MODE_RUNS=()
MODES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --experiment-ids)
      shift
      while [[ $# -gt 0 && "${1:0:2}" != "--" ]]; do
        EXPERIMENT_IDS+="${1} "
        shift
      done
      ;;
    --mode-runs)
      MODE_RUNS+=("$2")
      shift 2
      ;;
    --modes)
      shift
      while [[ $# -gt 0 && "${1:0:2}" != "--" ]]; do
        MODES+="${1} "
        shift
      done
      ;;
    -h|--help)
      cat <<EOF
Usage:
  $0 --config CONFIG.yaml \
     [--experiment-ids expA expB ...]
     [--mode-runs modeA:exp1,exp2 ...]
     [--modes modeA modeB ...]
     [--outdir analysis_out]

Notes:
  - Either --experiment-ids OR --mode-runs must be provided
  - Runs full pipeline: build → summarize → pairwise
EOF
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$CONFIG" ]]; then
  echo "ERROR: --config required" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

MASTER_DIR="$OUTDIR/master"
SUMMARY_DIR="$OUTDIR/summaries"
PAIRWISE_DIR="$OUTDIR/pairwise"

mkdir -p "$MASTER_DIR" "$SUMMARY_DIR" "$PAIRWISE_DIR"

# ---- build_all_runs ----
CMD=(
  "$PYTHON_BIN"
  "$SCRIPT_DIR/build_all_runs_table.py"
  --config "$CONFIG"
  --outdir "$MASTER_DIR"
)

if [[ -n "$EXPERIMENT_IDS" ]]; then
  # shellcheck disable=SC2206
  EXP_IDS_ARR=( $EXPERIMENT_IDS )
  CMD+=( --experiment-ids "${EXP_IDS_ARR[@]}" )
fi

if [[ -n "$MODES" ]]; then
  # shellcheck disable=SC2206
  MODES_ARR=( $MODES )
  CMD+=( --modes "${MODES_ARR[@]}" )
fi

for mr in "${MODE_RUNS[@]}"; do
  CMD+=( --mode-runs "$mr" )
done

echo "==> Building all_runs.csv"
"${CMD[@]}"

ALL_RUNS="$MASTER_DIR/all_runs.csv"

# ---- summarize ----
echo "==> Summarizing all modes"
"$PYTHON_BIN" "$SCRIPT_DIR/summarize_all_modes.py" \
  --input "$ALL_RUNS" \
  --outdir "$SUMMARY_DIR" \
  --with-omnibus-glmm

# ---- pairwise ----
echo "==> Running pairwise comparisons"
"$PYTHON_BIN" "$SCRIPT_DIR/pairwise_compare_modes.py" \
  --input "$ALL_RUNS" \
  --outdir "$PAIRWISE_DIR" \
  --pairs all

echo
echo "✅ Done. Outputs in:"
echo "  $OUTDIR/"