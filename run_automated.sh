#!/usr/bin/env bash
# Usage:
#   ./run_automated.sh PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE
#
# What it does:
#   2) WITH explanations:
#        ./run_all.sh PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE --LLM-active
#   3) WITHOUT explanations:
#        ./run_all.sh PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE --LLM-active --without-explanation
#   4) Metrics for WITH-explanations branches:
#        ./run_metrics_for_llm_branches.sh PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE with
#   5) Metrics for WITHOUT-explanations branches:
#        ./run_metrics_for_llm_branches.sh PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE without
#
# NOTE: You still run step 1 manually, once:
#   ./run_all.sh PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT

set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "Usage: $0 PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE" >&2
  exit 2
fi

PROJECTS_DIR="${1%/}"
REPOS_FILE="$2"
EXPERIMENT_ID="$3"
OUTPUT_ROOT="${4%/}"
CYCLES_FILE="$5"

mkdir -p "$OUTPUT_ROOT"
export TIMING_LOG="$(realpath "${OUTPUT_ROOT%/}")/timings_${EXPERIMENT_ID}.jsonl"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_ALL="${SCRIPT_DIR}/run_all.sh"
RUN_METRICS_LLMBR="${SCRIPT_DIR}/run_metrics_for_llm_branches.sh"

[[ -f "$RUN_ALL" ]] || { echo "run_all.sh not found: $RUN_ALL" >&2; exit 3; }
[[ -f "$RUN_METRICS_LLMBR" ]] || { echo "run_metrics_for_llm_branches.sh not found: $RUN_METRICS_LLMBR" >&2; exit 4; }
[[ -f "$REPOS_FILE" ]] || { echo "Repos file not found: $REPOS_FILE" >&2; exit 5; }
[[ -f "$CYCLES_FILE" ]] || { echo "Cycles file not found: $CYCLES_FILE" >&2; exit 6; }
mkdir -p "$OUTPUT_ROOT"

echo "### Automated — START"
echo "Projects dir : $PROJECTS_DIR"
echo "Repos file   : $REPOS_FILE"
echo "Experiment   : $EXPERIMENT_ID"
echo "Output root  : $OUTPUT_ROOT"
echo "Cycles file  : $CYCLES_FILE"
echo

echo "## 2) LLM pass WITH explanations"
"$RUN_ALL" "$PROJECTS_DIR" "$REPOS_FILE" "$EXPERIMENT_ID" "$OUTPUT_ROOT" "$CYCLES_FILE" --LLM-active

echo
echo "## 3) LLM pass WITHOUT explanations"
"$RUN_ALL" "$PROJECTS_DIR" "$REPOS_FILE" "$EXPERIMENT_ID" "$OUTPUT_ROOT" "$CYCLES_FILE" --LLM-active --without-explanation

echo
echo "## 4) Metrics for WITH-explanations branches"
"$RUN_METRICS_LLMBR" "$PROJECTS_DIR" "$REPOS_FILE" "$EXPERIMENT_ID" "$OUTPUT_ROOT" "$CYCLES_FILE" with

echo
echo "## 5) Metrics for WITHOUT-explanations branches"
"$RUN_METRICS_LLMBR" "$PROJECTS_DIR" "$REPOS_FILE" "$EXPERIMENT_ID" "$OUTPUT_ROOT" "$CYCLES_FILE" without

echo
echo "✅ Automated — DONE"
