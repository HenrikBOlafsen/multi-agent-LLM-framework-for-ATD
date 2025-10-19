#!/usr/bin/env bash
# Usage: ./run_automated.sh <EXPERIMENT_ID> <START_ITER> <STOP_ITER> <REPOS_FILE> <OUTPUT_ROOT>
#
# EXACT BEHAVIOR:
#   ./run_automated.sh expA 0 2 repos.txt results/
#     Iter 0: non-LLM(once) → LLM(with) → LLM(without)
#     Iter 1: non-LLM(with) → non-LLM(without) → LLM(with) → LLM(without)
#     Iter 2: non-LLM(with) → non-LLM(without)
#
#   ./run_automated.sh expA 2 4 repos.txt results/
#     Iter 2: LLM(with) → LLM(without)
#     Iter 3: non-LLM(with) → non-LLM(without) → LLM(with) → LLM(without)
#     Iter 4: non-LLM(with) → non-LLM(without)

set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "Usage: $0 <EXPERIMENT_ID> <START_ITER> <STOP_ITER> <REPOS_FILE> <OUTPUT_ROOT>" >&2
  exit 1
fi

EXPERIMENT_ID="$1"
START_ITER="$2"
STOP_ITER="$3"          # LLM runs up to STOP-1; metrics also at STOP
REPOS_FILE="$4"
OUTPUT_ROOT="$5"

# Validate iterations
num='^[0-9]+$'
if ! [[ $START_ITER =~ $num && $STOP_ITER =~ $num ]]; then
  echo "ERROR: START_ITER and STOP_ITER must be non-negative integers." >&2
  exit 2
fi
if (( START_ITER > STOP_ITER )); then
  echo "ERROR: START_ITER ($START_ITER) > STOP_ITER ($STOP_ITER)." >&2
  exit 3
fi

PROJECTS_DIR="projects_to_analyze/"
RUN_ALL="./run_all.sh"

if [[ ! -x "$RUN_ALL" ]]; then
  echo "Error: $RUN_ALL not found or not executable." >&2
  exit 4
fi
if [[ ! -f "$REPOS_FILE" ]]; then
  echo "Error: repos file '$REPOS_FILE' not found." >&2
  exit 5
fi

NOEXP_ID="${EXPERIMENT_ID}_without_explanation"

echo "### Automated runs (abort on first error)"
echo "Experiment ID         : $EXPERIMENT_ID"
echo "Start..Stop (LLM exclusive at STOP, metrics inclusive): $START_ITER..$STOP_ITER"
echo "Repos file            : $REPOS_FILE"
echo "Output root           : $OUTPUT_ROOT"
echo

run_all_required () {
  local iter="$1"
  local exp_id="$2"
  shift 2
  echo
  echo "===== $(date -Iseconds) | Iter=$iter | $RUN_ALL $PROJECTS_DIR $REPOS_FILE $iter $exp_id $OUTPUT_ROOT $* ====="
  "$RUN_ALL" "$PROJECTS_DIR" "$REPOS_FILE" "$iter" "$exp_id" "$OUTPUT_ROOT" "$@"
}

# LLM phase for BOTH modes at a given iteration
llm_both () {
  local iter="$1"
  run_all_required "$iter" "$EXPERIMENT_ID" --LLM-active
  run_all_required "$iter" "$NOEXP_ID" --LLM-active --without-explanations
}

# Non-LLM metrics for BOTH modes at a given iteration
metrics_both () {
  local iter="$1"
  run_all_required "$iter" "$EXPERIMENT_ID"
  run_all_required "$iter" "$NOEXP_ID" --without-explanations
}

# Non-LLM metrics ONCE (special for iter 0)
metrics_once_iter0 () {
  local iter="$1"   # should be 0
  run_all_required "$iter" "$EXPERIMENT_ID"
}

# ---------------- SCHEDULE ----------------

if (( START_ITER == 0 )); then
  # Iter 0: non-LLM ONCE, then LLM for both
  metrics_once_iter0 0
  if (( STOP_ITER > 0 )); then
    llm_both 0
  fi
  begin=1
else
  # Resuming: at START do LLM-only
  if (( START_ITER < STOP_ITER )); then
    llm_both "$START_ITER"
  fi
  begin=$(( START_ITER + 1 ))
fi

# Middle iterations: begin .. STOP-1 → metrics(both) then LLM(both)
if (( begin <= STOP_ITER - 1 )); then
  for (( i=begin; i<=STOP_ITER-1; i++ )); do
    metrics_both "$i"
    llm_both "$i"
  done
fi

# Final metrics at STOP (both modes), except the degenerate case START=STOP=0 already handled above
if ! (( START_ITER == 0 && STOP_ITER == 0 )); then
  metrics_both "$STOP_ITER"
fi

echo
echo "### Automation complete."
