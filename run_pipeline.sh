#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   run_pipeline.sh REPO_PATH BRANCH_NAME SRC_REL_PATH OUTPUT_DIR
#     [--LLM-active]
#     [--experiment-id EXP]          # required (both phases), used for naming branches per cycle
#     [--without-explanations]       # optional
#     [--cycles-file FILE]           # required only for --LLM-active
#
# NOTES:
# - Non-LLM phase runs analysis + metrics (no selection).
# - LLM phase loops over all cycle ids for this repo/branch found in cycles_to_analyze.txt
#   and creates a separate branch per cycle, named: fix-<cycle_id>-<EXP> (sanitized).

# ---- Helpers ----
err () { echo "ERROR: $*" >&2; exit 1; }
need () { command -v "$1" >/dev/null 2>&1 || err "Missing required tool: $1"; }
sanitize_branch () {
  # Replace anything not [A-Za-z0-9._/-] with '-' and squeeze repeats, trim leading '-'
  local s="${1// /-}"
  s="$(printf "%s" "$s" | tr -c 'A-Za-z0-9._/-' '-' | sed -E 's/-+/-/g; s#-+/#/#g; s#/-+#/#g; s#^-+##')"
  # Avoid trailing '/' or '.lock'
  s="${s%/}"
  printf "%s" "$s"
}
derive_slug () {
  local url
  url="$(git -C "$REPO_PATH" remote get-url origin 2>/dev/null || true)"
  if [[ "$url" =~ github.com[:/]+([^/]+)/([^.]+)(\.git)?$ ]]; then
    echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
  else
    err "Cannot derive owner/repo from 'origin' (url='$url')"
  fi
}
branch_exists () {
  # local and/or remote?
  local name="$1"
  git -C "$REPO_PATH" show-ref --verify --quiet "refs/heads/$name" && return 0
  git -C "$REPO_PATH" ls-remote --exit-code --heads origin "$name" >/dev/null 2>&1 && return 0
  return 1
}

# ---- Args ----
if [[ $# -lt 4 ]]; then
  echo "Usage: $0 REPO_PATH BRANCH_NAME SRC_REL_PATH OUTPUT_DIR [--LLM-active] [--experiment-id EXP] [--without-explanations] [--cycles-file FILE]" >&2
  exit 2
fi

REPO_PATH="$(cd "$1" && pwd)"
BRANCH_NAME="$2"
SRC_REL_PATH="$3"
OUTPUT_DIR="$4"; shift 4

LLM_ACTIVE=0
EXPERIMENT_ID=""
NO_EXPLAIN=0
OVERRIDE_CYCLES_FILE=""
BASELINE_BRANCH=""

i=0
while [[ $i -lt $# ]]; do
  i=$((i+1))
  arg="${!i}"
  case "$arg" in
    --LLM-active)
      LLM_ACTIVE=1
      ;;
    --experiment-id)
      j=$((i+1)); [[ $j -le $# ]] || err "--experiment-id needs a value"
      EXPERIMENT_ID="${!j}"; i=$((i+1))
      ;;
    --without-explanations|--without-explanation)
      NO_EXPLAIN=1
      ;;
    --cycles-file)
      j=$((i+1)); [[ $j -le $# ]] || err "--cycles-file needs a value"
      OVERRIDE_CYCLES_FILE="${!j}"; i=$((i+1))
      ;;
    --baseline-branch)
      j=$((i+1)); [[ $j -le $# ]] || err "--baseline-branch needs a value"
      BASELINE_BRANCH="${!j}"; i=$((i+1))
      ;;
    *)
      err "Unknown option: $arg"
      ;;
  esac
done

[[ -n "$EXPERIMENT_ID" ]] || err "Missing required: --experiment-id EXP"

# ---- Locations ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYZE_SH="${SCRIPT_DIR}/ATD_identification/analyze_cycles.sh"
QUALITY_SH="${SCRIPT_DIR}/code_quality_checker/quality_collect.sh"
EXPLAIN_PY="${SCRIPT_DIR}/explain_AS/explain_cycle.py"
EXPLAIN_MIN_PY="${SCRIPT_DIR}/explain_AS/explain_cycle_minimal.py"
OPENHANDS_SH="${SCRIPT_DIR}/run_OpenHands/run_OpenHands.sh"

[[ -f "$ANALYZE_SH"     ]] || err "Missing analyze script: $ANALYZE_SH"
[[ -f "$QUALITY_SH"     ]] || err "Missing quality script: $QUALITY_SH"
[[ -f "$EXPLAIN_PY"     ]] || err "Missing explain_cycle.py: $EXPLAIN_PY"
[[ -f "$EXPLAIN_MIN_PY" ]] || err "Missing explain_cycle_minimal.py: $EXPLAIN_MIN_PY"
[[ -f "$OPENHANDS_SH"   ]] || err "Missing OpenHands runner: $OPENHANDS_SH"

# ---- Output dirs ----
ATD_DIR="$OUTPUT_DIR/ATD_identification"
QC_DIR="$OUTPUT_DIR/code_quality_checks"
EXPLAIN_DIR_OUT="$OUTPUT_DIR/explain_AS/$([[ $NO_EXPLAIN -eq 1 ]] && echo without_explanations || echo with_explanations)"
OPENHANDS_DIR="$OUTPUT_DIR/openhands/$([[ $NO_EXPLAIN -eq 1 ]] && echo without_explanations || echo with_explanations)"
mkdir -p "$ATD_DIR" "$QC_DIR" "$EXPLAIN_DIR_OUT" "$OPENHANDS_DIR"

# ---- Repo setup ----
need git
git -C "$REPO_PATH" fetch --all --prune >/dev/null 2>&1 || true

# If this is a metrics-only run (non-LLM) and the target branch doesn't exist,
# copy metrics from the baseline branch instead of crashing.
if [[ $LLM_ACTIVE -eq 0 ]] && ! branch_exists "$BRANCH_NAME"; then
  [[ -n "$BASELINE_BRANCH" ]] || err "Branch '$BRANCH_NAME' not found and --baseline-branch not provided."

  echo "==> Target branch '$BRANCH_NAME' does not exist. Copying metrics from baseline '$BASELINE_BRANCH'."

  # results/<repo>/<baseline> (source) → results/<repo>/<branch> (dest)
  REPO_NAME="$(basename "$REPO_PATH")"
  RESULTS_REPO_DIR="$(dirname "$OUTPUT_DIR")"             # results/<repo>
  SRC_BASE_DIR="$RESULTS_REPO_DIR/$BASELINE_BRANCH"       # results/<repo>/<baseline>
  DST_BRANCH_DIR="$OUTPUT_DIR"                            # results/<repo>/<branch>

  mkdir -p "$DST_BRANCH_DIR"

  # Copy ATD + quality artifacts if present
  if [[ -d "$SRC_BASE_DIR/ATD_identification" ]]; then
    rsync -a --delete "$SRC_BASE_DIR/ATD_identification/" "$DST_BRANCH_DIR/ATD_identification/" || true
  fi
  if [[ -d "$SRC_BASE_DIR/code_quality_checks" ]]; then
    rsync -a --delete "$SRC_BASE_DIR/code_quality_checks/" "$DST_BRANCH_DIR/code_quality_checks/" || true
  fi

  # Leave a marker for traceability
  echo "copied_from_baseline=$BASELINE_BRANCH" > "$DST_BRANCH_DIR/.copied_metrics_marker"
  date -Iseconds >> "$DST_BRANCH_DIR/.copied_metrics_marker"

  echo "==> Metrics copied from baseline. Skipping analysis for missing branch '$BRANCH_NAME'."
  exit 0
fi

# Normal path: switch to the branch and continue
git -C "$REPO_PATH" checkout -q "$BRANCH_NAME"
git -C "$REPO_PATH" reset --hard -q "origin/$BRANCH_NAME" || true
echo "==> On $(git -C "$REPO_PATH" rev-parse --abbrev-ref HEAD) @ $(git -C "$REPO_PATH" rev-parse --short HEAD)"
REPO_NAME="$(basename "$REPO_PATH")"


# ---- Non-LLM phase ----
if [[ $LLM_ACTIVE -eq 0 ]]; then
  echo "== Step 1: Identify cyclic dependencies =="
  export LANGUAGE=python
  bash "$ANALYZE_SH" "$REPO_PATH" "$SRC_REL_PATH" "$ATD_DIR"

  CYCLES_JSON="$ATD_DIR/module_cycles.json"
  [[ -f "$CYCLES_JSON" ]] || err "Expected cycles JSON not found: $CYCLES_JSON"

  echo "== Step 2: Collect code quality metrics =="
  OUT_DIR="$QC_DIR" bash "$QUALITY_SH" "$REPO_PATH" "$BRANCH_NAME" "$SRC_REL_PATH" || true

  SINGLE_SUMMARIZER="${SCRIPT_DIR}/code_quality_checker/quality_single_summary.py"
  [[ -f "$SINGLE_SUMMARIZER" ]] || SINGLE_SUMMARIZER="${SCRIPT_DIR}/quality_single_summary.py"

  METRICS_JSON="$QC_DIR/metrics.json"
  if [[ -f "$SINGLE_SUMMARIZER" ]]; then
    python3 "$SINGLE_SUMMARIZER" "$QC_DIR" "$METRICS_JSON" || true
    echo "Metrics summary: $METRICS_JSON"
  fi

  echo "Non-LLM phase complete."
  exit 0
fi

# ---- LLM phase ----
[[ -n "$OVERRIDE_CYCLES_FILE" && -f "$OVERRIDE_CYCLES_FILE" ]] || err "--LLM-active requires --cycles-file <cycles_to_analyze.txt>"

CYCLES_JSON="$ATD_DIR/module_cycles.json"
[[ -f "$CYCLES_JSON" ]] || err "CYCLES_JSON not found. Run non-LLM phase first: $CYCLES_JSON"

# Collect all cycle IDs for this repo+branch
CYCLE_IDS=()
while IFS=$' \t' read -r r b cid _ || [[ -n "${r:-}" ]]; do
  [[ -z "${r:-}" || "$r" =~ ^# ]] && continue
  if [[ "$r" == "$REPO_NAME" && "$b" == "$BRANCH_NAME" ]]; then
    CYCLE_IDS+=("$cid")
  fi
done < "$OVERRIDE_CYCLES_FILE"

if [[ ${#CYCLE_IDS[@]} -eq 0 ]]; then
  echo "== No cycles for ${REPO_NAME}@${BRANCH_NAME} in $OVERRIDE_CYCLES_FILE; skipping LLM =="
  exit 0
fi

echo "== LLM: cycles to process for ${REPO_NAME}@${BRANCH_NAME}: ${CYCLE_IDS[*]} =="

for CYCLE_ID in "${CYCLE_IDS[@]}"; do
  echo
  echo "== LLM Step 1: Generate refactoring prompt for $CYCLE_ID =="

  EXPLAIN_SUBDIR="$EXPLAIN_DIR_OUT/$CYCLE_ID"
  OPENHANDS_SUBDIR="$OPENHANDS_DIR/$CYCLE_ID"
  mkdir -p "$EXPLAIN_SUBDIR" "$OPENHANDS_SUBDIR"

  FULL_LOG="$EXPLAIN_SUBDIR/full.log"
  FINAL_PROMPT="$EXPLAIN_SUBDIR/prompt.txt"

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
  [[ -f "$PROMPT_TO_USE" ]] || err "Prompt not found at $PROMPT_TO_USE"

  # Branch per cycle (aligned with RQ scripts): cycle-fix-<exp-label>-<cycle_id>
  SAFE_CYCLE="$(sanitize_branch "$CYCLE_ID")"
  if [[ $NO_EXPLAIN -eq 1 ]]; then
    EXP_LABEL="$(sanitize_branch "${EXPERIMENT_ID}_without_explanation")"
  else
    EXP_LABEL="$(sanitize_branch "${EXPERIMENT_ID}")"
  fi
  NEW_BRANCH="$(sanitize_branch "cycle-fix-${EXP_LABEL}-${SAFE_CYCLE}")"


  echo "== LLM Step 2: Perform refactoring with OpenHands for $CYCLE_ID =="
  SLUG="$(derive_slug)" || err "Could not derive owner/repo from 'origin' remote."

  echo "Repo slug   : $SLUG"
  echo "Base branch : $BRANCH_NAME"
  echo "New branch  : $NEW_BRANCH"
  echo "Prompt      : $PROMPT_TO_USE"
  echo "Logs →      : $OPENHANDS_SUBDIR"

  LOG_DIR="$OPENHANDS_SUBDIR" bash "$OPENHANDS_SH" "$SLUG" "$BRANCH_NAME" "$NEW_BRANCH" "$PROMPT_TO_USE"

  echo "✅ Done $CYCLE_ID → branch: $NEW_BRANCH ; prompt: $PROMPT_TO_USE ; logs: $OPENHANDS_SUBDIR"
done

echo
echo "✅ LLM phase complete for ${#CYCLE_IDS[@]} cycle(s)."
