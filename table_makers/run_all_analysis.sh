#!/usr/bin/env bash
set -euo pipefail

CONFIG=""
ANALYSIS_PLAN=""
OUTDIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="$2"
      shift 2
      ;;
    --analysis-plan)
      ANALYSIS_PLAN="$2"
      shift 2
      ;;
    --outdir)
      OUTDIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$CONFIG" || -z "$ANALYSIS_PLAN" || -z "$OUTDIR" ]]; then
  echo "Usage:" >&2
  echo "  bash table_makers/run_all_analysis.sh --config <path> --analysis-plan <path> --outdir <dir>" >&2
  exit 2
fi

mkdir -p "$OUTDIR"

python3 table_makers/make_all_analysis.py \
  --config "$CONFIG" \
  --analysis-plan "$ANALYSIS_PLAN" \
  --outdir "$OUTDIR"