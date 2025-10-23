#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run_all.sh PATH_TO_REPOS REPOS_FILE EXPERIMENT_ID [OUTPUT_ROOT] [CYCLES_FILE] [--LLM-active] [--without-explanations]
#
# Examples:
#   # Non-LLM phase for experiment "expA" (builds module_cycles.json + metrics)
#   ./run_all.sh projects_to_analyze/ repos.txt expA results/
#
#   # LLM phase for the same experiment, honoring a cycles list
#   ./run_all.sh projects_to_analyze/ repos.txt expA results/ cycles_to_analyze.txt --LLM-active
#
# REPOS_FILE lines:  <repo_name>  <base_branch>  <src_rel_path>
#   kombu main kombu
#   click main src/click

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Args ---
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 PATH_TO_REPOS REPOS_FILE EXPERIMENT_ID [OUTPUT_ROOT] [CYCLES_FILE] [--LLM-active] [--without-explanations]" >&2
  exit 2
fi

PATH_TO_REPOS="${1%/}"
REPOS_FILE="$2"
EXPERIMENT_ID="$3"
OUTPUT_ROOT="${4:-results}"

# Optional 5th positional: cycles_to_analyze.txt (must not be a flag)
CYCLES_FILE=""
if [[ -n "${5:-}" && "${5:0:2}" != "--" && -f "${5}" ]]; then
  CYCLES_FILE="$5"
  shift_for_flags=6
else
  shift_for_flags=5
fi

LLM_ACTIVE=0
if [[ "${!shift_for_flags:-}" == "--LLM-active" ]]; then
  LLM_ACTIVE=1
fi

PASS_NOEXPLAIN=""
for a in "${@:${shift_for_flags}}"; do
  if [[ "$a" == "--without-explanations" || "$a" == "--without-explanation" ]]; then
    PASS_NOEXPLAIN="--without-explanations"
  fi
done

# --- Binaries/paths ---
RUN_PIPELINE="${SCRIPT_DIR}/run_pipeline.sh"

[[ -f "$REPOS_FILE" ]] || { echo "Repos file not found: $REPOS_FILE" >&2; exit 3; }

mkdir -p "$OUTPUT_ROOT"

echo "### Batch run"
echo "Repos file     : $REPOS_FILE"
echo "Projects root  : $PATH_TO_REPOS"
echo "Experiment     : $EXPERIMENT_ID"
echo "Output root    : $OUTPUT_ROOT"
echo "Cycles file    : ${CYCLES_FILE:-<none>}"
echo "LLM active     : $LLM_ACTIVE"
echo

# Read repos list: repo_name  branch  src_rel
while read -r REPO_NAME BRANCH_NAME SRC_REL || [[ -n "${REPO_NAME:-}" ]]; do
  [[ -z "${REPO_NAME:-}" || "$REPO_NAME" =~ ^# ]] && continue

  REPO_DIR="${PATH_TO_REPOS%/}/$REPO_NAME"
  [[ -d "$REPO_DIR" ]] || { echo "Skip (not found): $REPO_DIR" >&2; continue; }

  OUT_DIR="${OUTPUT_ROOT%/}/$REPO_NAME/$BRANCH_NAME"
  mkdir -p "$OUT_DIR"

  echo
  echo "===== $(date -Iseconds) | ${REPO_NAME}@${BRANCH_NAME} | exp=${EXPERIMENT_ID} ====="

  if [[ $LLM_ACTIVE -eq 0 ]]; then
    # Non-LLM phase
    if [[ -n "$CYCLES_FILE" ]]; then
      bash "$RUN_PIPELINE" "$REPO_DIR" "$BRANCH_NAME" "$SRC_REL" "$OUT_DIR" \
        --experiment-id "$EXPERIMENT_ID" --cycles-file "$CYCLES_FILE"
    else
      bash "$RUN_PIPELINE" "$REPO_DIR" "$BRANCH_NAME" "$SRC_REL" "$OUT_DIR" \
        --experiment-id "$EXPERIMENT_ID"
    fi
  else
    # LLM phase
    if [[ -n "$CYCLES_FILE" ]]; then
      bash "$RUN_PIPELINE" "$REPO_DIR" "$BRANCH_NAME" "$SRC_REL" "$OUT_DIR" \
        --LLM-active --experiment-id "$EXPERIMENT_ID" --cycles-file "$CYCLES_FILE" $PASS_NOEXPLAIN
    else
      echo "ERROR: --LLM-active requires a cycles file (cycles_to_analyze.txt)" >&2
      exit 4
    fi
  fi

done < "$REPOS_FILE"

echo
echo "✅ All done."
