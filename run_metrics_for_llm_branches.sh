#!/usr/bin/env bash
set -euo pipefail
# Usage:
#   ./run_metrics_for_llm_branches.sh PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE with|without
#
# Examples:
#   ./run_metrics_for_llm_branches.sh projects_to_analyze/ repos.txt expA results/ cycles_to_analyze.txt with
#   ./run_metrics_for_llm_branches.sh projects_to_analyze/ repos.txt expA results/ cycles_to_analyze.txt without
#
# It derives the branch names created by the LLM passes:
#   WITH explanations   → cycle-fix-<exp>-<cycle_id>
#   WITHOUT explanations→ cycle-fix-<exp>_without_explanation-<cycle_id>
# and runs the non-LLM metrics pipeline on those branches.

if [[ $# -ne 6 ]]; then
  echo "Usage: $0 PROJECTS_DIR REPOS_FILE EXPERIMENT_ID OUTPUT_ROOT CYCLES_FILE with|without" >&2
  exit 2
fi

PROJECTS_DIR="${1%/}"
REPOS_FILE="$2"
EXPERIMENT_ID="$3"
OUTPUT_ROOT="${4%/}"
CYCLES_FILE="$5"
MODE="$6"  # with|without

[[ "$MODE" == "with" || "$MODE" == "without" ]] || { echo "MODE must be 'with' or 'without'." >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_PIPELINE="${SCRIPT_DIR}/run_pipeline.sh"

[[ -f "$REPOS_FILE" ]]  || { echo "Repos file not found: $REPOS_FILE" >&2; exit 3; }
[[ -f "$CYCLES_FILE" ]] || { echo "Cycles file not found: $CYCLES_FILE" >&2; exit 4; }
[[ -f "$RUN_PIPELINE" ]]|| { echo "run_pipeline.sh not found: $RUN_PIPELINE" >&2; exit 5; }

sanitize() {
  local s="${1// /-}"
  s="$(printf "%s" "$s" | tr -c 'A-Za-z0-9._/-' '-' | sed -E 's/-+/-/g; s#-+/#/#g; s#/-+#/#g; s#^-+##')"
  s="${s%/}"
  printf "%s" "$s"
}

# Map repo -> (base_branch, src_rel) from repos.txt
declare -A BASE_BRANCH SRC_REL
while read -r repo base src || [[ -n "${repo:-}" ]]; do
  [[ -z "${repo:-}" || "$repo" =~ ^# ]] && continue
  BASE_BRANCH["$repo"]="$base"
  SRC_REL["$repo"]="$src"
done < "$REPOS_FILE"

processed=0

# For each cycle row matching an existing repo/branch, compute the new branch name and run metrics
while read -r repo branch cid _ || [[ -n "${repo:-}" ]]; do
  [[ -z "${repo:-}" || "$repo" =~ ^# ]] && continue
  [[ "${BASE_BRANCH[$repo]:-}" == "$branch" ]] || continue

  REPO_DIR="${PROJECTS_DIR}/${repo}"
  [[ -d "$REPO_DIR" ]] || { echo "Skip (repo dir not found): $REPO_DIR" >&2; continue; }

  suffix="$EXPERIMENT_ID"
  if [[ "$MODE" == "without" ]]; then
    suffix="${EXPERIMENT_ID}_without_explanation"
  fi
  NEW_BRANCH="$(sanitize "cycle-fix-${suffix}-${cid}")"

  OUT_DIR="${OUTPUT_ROOT}/${repo}/${NEW_BRANCH}"
  mkdir -p "$OUT_DIR"

  echo
  echo "== Metrics for ${repo}@${NEW_BRANCH} (from cycle ${cid}) =="

  # This is a non-LLM pass; we still pass --experiment-id (required by run_pipeline.sh)
  bash "$RUN_PIPELINE" "$REPO_DIR" "$NEW_BRANCH" "${SRC_REL[$repo]}" "$OUT_DIR" \
    --experiment-id "$EXPERIMENT_ID" \
    --baseline-branch "${BASE_BRANCH[$repo]}"

  processed=$((processed+1))
done < "$CYCLES_FILE"

echo
echo "✅ Metrics collection complete for $MODE explanations branches ($processed branches)."
