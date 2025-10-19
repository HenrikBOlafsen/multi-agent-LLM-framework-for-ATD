#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   run_pipeline.sh REPO_PATH BRANCH_NAME SRC_REL_PATH OUTPUT_DIR \
#     [--LLM-active [--new-branch NEW_BRANCH] [--experiment EXP_ID --iter N]] \
#     [--without-explanations|--without-explanation]
#
# Behavior:
#   - Without --LLM-active: run non-LLM phase (cycles + quality + select).
#   - With --LLM-active: generate prompt (full or minimal) + run OpenHands.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

if [[ $# -lt 4 ]]; then
  echo "Usage: $0 REPO_PATH BRANCH_NAME SRC_REL_PATH OUTPUT_DIR [flags]" >&2
  exit 2
fi

REPO_PATH="${1%/}"
BRANCH_NAME="$2"
SRC_REL_PATH="${3%/}"
OUTPUT_DIR="${4%/}"

# Defaults / flags
LLM_ACTIVE=0
NEW_BRANCH=""
EXPERIMENT_ID=""
ITER_VAL=""
NO_EXPLAIN=0

# Parse long options starting at $5
i=5
while [[ $i -le $# ]]; do
  arg="${!i}"
  case "$arg" in
    --LLM-active)
      LLM_ACTIVE=1
      ;;
    --new-branch)
      j=$((i+1)); [[ $j -le $# ]] || { echo "--new-branch needs a value" >&2; exit 2; }
      NEW_BRANCH="${!j}"; i=$((i+1))
      ;;
    --experiment)
      j=$((i+1)); [[ $j -le $# ]] || { echo "--experiment needs a value" >&2; exit 2; }
      EXPERIMENT_ID="${!j}"; i=$((i+1))
      ;;
    --iter)
      j=$((i+1)); [[ $j -le $# ]] || { echo "--iter needs a value" >&2; exit 2; }
      ITER_VAL="${!j}"; i=$((i+1))
      ;;
    --without-explanations|--without-explanation)
      NO_EXPLAIN=1
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
  i=$((i+1))
done

# Tool/script locations (prefer subdirs, then fall back to root)
ANALYZE_SH="${SCRIPT_DIR}/ATD_identification/cycle_extractor/analyze_cycles.sh"
QUALITY_SH="${SCRIPT_DIR}/code_quality_checker/quality_collect.sh"
SELECT_PY="${SCRIPT_DIR}/explain_AS/select_cycle.py"
EXPLAIN_PY="${SCRIPT_DIR}/explain_AS/explain_cycle.py"
EXPLAIN_MIN_PY="${SCRIPT_DIR}/explain_AS/explain_cycle_minimal.py"
OPENHANDS_SH="${SCRIPT_DIR}/run_OpenHands/run_OpenHands.sh"
[[ -x "$ANALYZE_SH" ]] || ANALYZE_SH="${SCRIPT_DIR}/analyze_cycles.sh"
[[ -x "$QUALITY_SH" ]] || QUALITY_SH="${SCRIPT_DIR}/quality_collect.sh"
[[ -f "$SELECT_PY"  ]] || SELECT_PY="${SCRIPT_DIR}/select_cycle.py"
[[ -f "$EXPLAIN_PY" ]] || EXPLAIN_PY="${SCRIPT_DIR}/explain_cycle.py"
[[ -f "$EXPLAIN_MIN_PY" ]] || EXPLAIN_MIN_PY="${SCRIPT_DIR}/explain_cycle_minimal.py"
[[ -x "$OPENHANDS_SH" ]] || OPENHANDS_SH="${SCRIPT_DIR}/run_OpenHands.sh"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 1; }; }
need git
[[ -d "$REPO_PATH" ]] || { echo "Repo path not found: $REPO_PATH" >&2; exit 1; }

# Layout
ATD_DIR="$OUTPUT_DIR/ATD_identification"
QC_DIR="$OUTPUT_DIR/code_quality_checks"

# Separate outputs by mode to avoid overwriting between runs
# NO_EXPLAIN=1 when --without-explanations was passed
if [[ $NO_EXPLAIN -eq 1 ]]; then
  MODE_SUBDIR="without_explanation"
else
  MODE_SUBDIR="with_explanation"
fi

EXPLAIN_DIR_OUT="$OUTPUT_DIR/explain_AS/$MODE_SUBDIR"
OPENHANDS_DIR="$OUTPUT_DIR/openhands/$MODE_SUBDIR"

mkdir -p "$ATD_DIR" "$QC_DIR" "$EXPLAIN_DIR_OUT" "$OPENHANDS_DIR"


err() { echo "ERROR: $*"; exit 1; }

derive_slug() {
  local url; url="$(git -C "$REPO_PATH" remote get-url origin 2>/dev/null || true)"; [[ -n "$url" ]] || return 1
  case "$url" in
    https://github.com/*) echo "${url#https://github.com/}" | sed 's/\.git$//' ;;
    http://github.com/*)  echo "${url#http://github.com/}"  | sed 's/\.git$//' ;;
    git@github.com:*)     echo "${url#git@github.com:}"     | sed 's/\.git$//' ;;
    *) return 1 ;;
  esac
}

newest_prompt_in() {
  local dir="$1"
  if compgen -G "$dir/"'*_prompt.txt' >/dev/null; then
    ls -t "$dir/"*_prompt.txt | head -n1
  elif compgen -G "$dir/"'*.txt' >/dev/null; then
    ls -t "$dir/"*.txt | head -n1
  else
    echo ""
  fi
}

echo "==> Switching $REPO_PATH to branch '$BRANCH_NAME'"
# Ensure a clean working tree (you said it's fine to discard changes)
echo "==> Ensuring clean working tree in $REPO_PATH (reset --hard; clean -fdx)"
git -C "$REPO_PATH" reset --hard
git -C "$REPO_PATH" clean -fdx

# Fetch and switch ONLY if the branch really exists (avoid fabricating it)
git -C "$REPO_PATH" fetch --all --quiet || true
if git -C "$REPO_PATH" rev-parse --verify --quiet "origin/$BRANCH_NAME" >/dev/null; then
  git -C "$REPO_PATH" switch -C "$BRANCH_NAME" "origin/$BRANCH_NAME"
elif git -C "$REPO_PATH" rev-parse --verify --quiet "$BRANCH_NAME" >/dev/null; then
  git -C "$REPO_PATH" switch "$BRANCH_NAME"
else
  echo "ERROR: Branch '$BRANCH_NAME' not found on origin and no local branch exists."
  echo "       Did the LLM step push to another remote/fork? Remotes:"
  git -C "$REPO_PATH" remote -v || true
  exit 1
fi

echo "==> On $(git -C "$REPO_PATH" rev-parse --abbrev-ref HEAD) @ $(git -C "$REPO_PATH" rev-parse --short HEAD)"

if [[ $LLM_ACTIVE -eq 0 ]]; then
  # -------------------------- Non-LLM steps ----------------------------------
  [[ -x "$ANALYZE_SH" ]] || err "Not executable: $ANALYZE_SH"
  [[ -x "$QUALITY_SH" ]] || err "Not executable: $QUALITY_SH"
  [[ -f "$SELECT_PY"  ]] || err "Missing: $SELECT_PY"

  echo "== Step 1: Identify cyclic dependencies =="
  export LANGUAGE=python
  bash "$ANALYZE_SH" "$REPO_PATH" "$SRC_REL_PATH" "$ATD_DIR"

  CYCLES_JSON="$ATD_DIR/module_cycles.json"
  [[ -f "$CYCLES_JSON" ]] || err "Expected cycles JSON not found: $CYCLES_JSON"

  echo "== Step 2: Collect code quality metrics =="
  echo "TEMPORARILY SKIPPED TO SPEED UP TESTING"
  OUT_DIR="$QC_DIR" bash "$QUALITY_SH" "$REPO_PATH" "$BRANCH_NAME" "$SRC_REL_PATH" || true

  SINGLE_SUMMARIZER="${SCRIPT_DIR}/code_quality_checker/quality_single_summary.py"
  [[ -f "$SINGLE_SUMMARIZER" ]] || SINGLE_SUMMARIZER="${SCRIPT_DIR}/quality_single_summary.py"

  METRICS_JSON="$QC_DIR/metrics.json"
  python3 "$SINGLE_SUMMARIZER" "$QC_DIR" "$METRICS_JSON" || true
  echo "Metrics summary: $METRICS_JSON"

  echo "== Step 3: Select representative cycle =="
  need python3
  CYCLE_ID="$(python3 "$SELECT_PY" "$CYCLES_JSON" || true)"

  if [[ -z "${CYCLE_ID:-}" ]]; then
    # No representative cycle → repo is DONE for this branch
    DONE_FILE="$OUTPUT_DIR/.repo_done"
    {
      echo "timestamp: $(date -Iseconds)"
      echo "reason: no representative cycles remain"
      echo "branch: $BRANCH_NAME"
    } > "$DONE_FILE"
    echo "✅ No cycles remain. Marked as done: $DONE_FILE"
    echo "Non-LLM phase complete. Nothing to refactor."
    exit 0
  fi

  echo "Chosen cycle: $CYCLE_ID"
  echo "Non-LLM phase complete. Re-run with --LLM-active to continue."
  exit 0
fi

# ------------------------------ LLM steps ------------------------------------
[[ -f "$EXPLAIN_PY" ]] || err "Missing: $EXPLAIN_PY"
[[ -f "$EXPLAIN_MIN_PY" ]] || err "Missing: $EXPLAIN_MIN_PY"
[[ -x "$OPENHANDS_SH" ]] || err "Not executable: $OPENHANDS_SH"

# If NEW_BRANCH not given, derive from experiment + iter
if [[ -z "$NEW_BRANCH" ]]; then
  [[ -n "$EXPERIMENT_ID" && -n "$ITER_VAL" ]] || err "For auto branch naming, provide --experiment EXP_ID and --iter N, or pass --new-branch."
  NEW_BRANCH="fix-cycle-$((ITER_VAL + 1))-$EXPERIMENT_ID"
fi

CYCLES_JSON="$ATD_DIR/module_cycles.json"
[[ -f "$CYCLES_JSON" ]] || err "CYCLES_JSON not found. Run non-LLM phase first: $CYCLES_JSON"

echo "== LLM Step 1: Generate refactoring prompt =="
if [[ -z "${CYCLE_ID:-}" ]]; then
  need python3
  CYCLE_ID="$(python3 "$SELECT_PY" "$CYCLES_JSON" || true)"
  [[ -n "${CYCLE_ID:-}" ]] || err "Failed to determine representative cycle from: $CYCLES_JSON"
fi
FULL_LOG="$EXPLAIN_DIR_OUT/${CYCLE_ID}_full.log"
FINAL_PROMPT="$EXPLAIN_DIR_OUT/${CYCLE_ID}_prompt.txt"

if [[ $NO_EXPLAIN -eq 1 ]]; then
  echo "== Using minimal prompt generator (no explanations) =="
  python3 "$EXPLAIN_MIN_PY" \
    --repo-root "$REPO_PATH" \
    --src-root "$SRC_REL_PATH" \
    --cycle-json "$CYCLES_JSON" \
    --cycle-id "$CYCLE_ID" \
    --out-prompt "$FINAL_PROMPT" \
    2>&1 | tee "$FULL_LOG"
else
  echo "== Using full explanation generator =="
  python3 "$EXPLAIN_PY" \
    --repo-root "$REPO_PATH" \
    --src-root "$SRC_REL_PATH" \
    --cycle-json "$CYCLES_JSON" \
    --cycle-id "$CYCLE_ID" \
    --out-prompt "$FINAL_PROMPT" \
    2>&1 | tee "$FULL_LOG"
fi

PROMPT_TO_USE="${PROMPT_PATH:-$FINAL_PROMPT}"
if [[ ! -f "$PROMPT_TO_USE" ]]; then
  echo "ERROR: Prompt not found at $PROMPT_TO_USE" >&2
  exit 2
fi

echo "== LLM Step 2: Perform refactoring with OpenHands =="
SLUG="$(derive_slug)" || err "Could not derive owner/repo from 'origin' remote."

echo "Repo slug   : $SLUG"
echo "Base branch : $BRANCH_NAME"
echo "New branch  : $NEW_BRANCH"
echo "Prompt      : $PROMPT_TO_USE"
echo "Logs →      : $OPENHANDS_DIR"

LOG_DIR="$OPENHANDS_DIR" bash "$OPENHANDS_SH" "$SLUG" "$BRANCH_NAME" "$NEW_BRANCH" "$PROMPT_TO_USE"

echo
echo "✅ LLM phase complete."
echo "  • Prompt         : $PROMPT_TO_USE"
echo "  • OpenHands logs : $OPENHANDS_DIR"
