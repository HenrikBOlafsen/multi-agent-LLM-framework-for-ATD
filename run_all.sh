#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   run_all.sh PATH_TO_REPOS REPOS_FILE REFACTORING_ITERATION EXPERIMENT_ID [OUTPUT_ROOT] [--LLM-active]
#
# Examples:
#   # Non-LLM phase for experiment "expA"
#   run_all.sh projects_to_analyze/ repos.txt 0 expA results/
#
#   # LLM phase (creates next branch fix-cycle-1-expA from main)
#   run_all.sh projects_to_analyze/ repos.txt 0 expA results/ --LLM-active
#
# REPOS_FILE lines:  repo_name  main_branch  src_rel_path
#   kombu main kombu
#   click main src/click
#
# Cloning:
#   If PATH_TO_REPOS/repo_name is missing and CLONE_PREFIX is set
#   (e.g., export CLONE_PREFIX="git@github.com:myuser/"), it clones repo_name.git.

PATH_TO_REPOS="${1%/}"
REPOS_FILE="$2"
ITER="$3"
EXPERIMENT_ID="$4"
OUTPUT_ROOT="${5:-results}"
LLM_ACTIVE=0
if [[ "${6:-}" == "--LLM-active" ]]; then
  LLM_ACTIVE=1
fi

# Collect pass-through for without-explanations (accept either spelling)
PASS_NOEXPLAIN=""
for a in "$@"; do
  if [[ "$a" == "--without-explanations" || "$a" == "--without-explanation" ]]; then
    PASS_NOEXPLAIN="--without-explanations"
  fi
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
RUN_PIPELINE="${SCRIPT_DIR}/run_pipeline.sh"

[[ -x "$RUN_PIPELINE" ]] || { echo "run_pipeline.sh not found/executable at $RUN_PIPELINE" >&2; exit 1; }
[[ -f "$REPOS_FILE" ]] || { echo "Repos file not found: $REPOS_FILE" >&2; exit 1; }

branch_for_iter() {
  local main_branch="$1"
  local it="$2"
  local exp="$3"
  if [[ "$it" -eq 0 ]]; then
    echo "$main_branch"
  else
    echo "fix-cycle-$it-$exp"
  fi
}
next_branch_after_iter() {
  local it="$1"
  local exp="$2"
  echo "fix-cycle-$((it + 1))-$exp"
}

while IFS=$' \t' read -r REPO_NAME MAIN_BRANCH SRC_REL || [[ -n "${REPO_NAME:-}" ]]; do
  [[ -z "${REPO_NAME:-}" ]] && continue
  [[ "$REPO_NAME" =~ ^# ]] && continue

  REPO_DIR="${PATH_TO_REPOS}/${REPO_NAME}"
  if [[ ! -d "$REPO_DIR" ]]; then
    if [[ -n "${CLONE_PREFIX:-}" ]]; then
      echo "==> Cloning ${REPO_NAME} into ${REPO_DIR}"
      git clone "${CLONE_PREFIX}${REPO_NAME}.git" "$REPO_DIR"
    else
      echo "WARN: Repo not found and CLONE_PREFIX unset; skipping: $REPO_NAME"
      continue
    fi
  fi

  BRANCH_NAME="$(branch_for_iter "$MAIN_BRANCH" "$ITER" "$EXPERIMENT_ID")"
  OUT_DIR="${OUTPUT_ROOT%/}/${REPO_NAME}/${BRANCH_NAME}"
  mkdir -p "$OUT_DIR"

  echo
  echo "==================== ${REPO_NAME} :: iter ${ITER} :: exp ${EXPERIMENT_ID} ===================="
  echo "Repo dir   : $REPO_DIR"
  echo "Branch     : $BRANCH_NAME"
  echo "Src rel    : $SRC_REL"
  echo "Output dir : $OUT_DIR"
  echo "LLM active : $LLM_ACTIVE"
  echo "============================================================================================="

  if [[ $LLM_ACTIVE -eq 0 ]]; then
    # Non-LLM phase
    bash "$RUN_PIPELINE" "$REPO_DIR" "$BRANCH_NAME" "$SRC_REL" "$OUT_DIR"
  else
    # LLM phase → create next iter branch with experiment id
    NEW_BRANCH="$(next_branch_after_iter "$ITER" "$EXPERIMENT_ID")"
    bash "$RUN_PIPELINE" "$REPO_DIR" "$BRANCH_NAME" "$SRC_REL" "$OUT_DIR" \
      --LLM-active --new-branch "$NEW_BRANCH" $PASS_NOEXPLAIN
    # (Alternative: omit --new-branch and let run_pipeline derive it)
    # bash "$RUN_PIPELINE" "$REPO_DIR" "$BRANCH_NAME" "$SRC_REL" "$OUT_DIR" \
    #   --LLM-active --experiment "$EXPERIMENT_ID" --iter "$ITER" $PASS_NOEXPLAIN
  fi

done < "$REPOS_FILE"

echo
echo "✅ All done."

# Notify via ntfy.sh (optional)
if command -v curl >/dev/null 2>&1; then
  curl -fsS -d "ATD batch finished (exp=${EXPERIMENT_ID:-?}, iter=${ITER:-?})" https://ntfy.sh/my-atd-build-abc123 >/dev/null 2>&1 || true
fi