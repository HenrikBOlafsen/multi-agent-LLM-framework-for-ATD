#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   run_pipeline.sh REPO_PATH BRANCH_NAME SRC_REL_PATH OUTPUT_DIR
#     [--LLM-active]
#     [--experiment-id EXP]          # required (both phases), used for naming branches per cycle
#     [--without-explanations]       # optional (LLM), generates "_without_explanation" exp label
#     [--cycles-file FILE]           # required only for --LLM-active
#     [--baseline-branch NAME]       # optional (non-LLM): if target branch missing, copy metrics from baseline
#
# NOTES:
# - Non-LLM phase runs analysis + metrics for OUTPUT_DIR (= results/<repo>/<branch>).
# - LLM phase loops cycles in cycles_to_analyze.txt and, for each cycle, creates a new branch:
#       cycle-fix-<exp>-<cycle_id>
#   and writes explain/OpenHands artifacts under:
#       results/<repo>/cycle-fix-<exp>-<cycle_id>/
#
# Environment used by run_OpenHands.sh (if present):
#   GITHUB_TOKEN, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, OPENHANDS_IMAGE, RUNTIME_IMAGE, etc.

# ---- Helpers ----
err () { echo "ERROR: $*" >&2; exit 1; }
need () { command -v "$1" >/dev/null 2>&1 || err "Missing required tool: $1"; }
sanitize_branch () {
  local s="${1// /-}"
  s="$(printf "%s" "$s" | tr -c 'A-Za-z0-9._/-' '-' | sed -E 's/-+/-/g; s#-+/#/#g; s#/-+#/#g; s#^-+##')"
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
  local name="$1"
  git -C "$REPO_PATH" show-ref --verify --quiet "refs/heads/$name" && return 0
  git -C "$REPO_PATH" ls-remote --exit-code --heads origin "$name" >/dev/null 2>&1 && return 0
  return 1
}
ts() { date -Iseconds; }
write_explain_status () {
  # $1 dir, $2 outcome, $3 reason
  local d="$1"; shift
  local outcome="${1:-}"; shift || true
  local reason="${1:-}"
  mkdir -p "$d"
  {
    echo "{"
    echo "  \"timestamp\": \"$(ts)\","
    echo "  \"phase\": \"explain\","
    echo "  \"outcome\": \"${outcome}\","
    echo "  \"reason\": \"${reason}\""
    echo "}"
  } > "$d/status.json"
}

# ---- Args ----
if [[ $# -lt 4 ]]; then
  echo "Usage: $0 REPO_PATH BRANCH_NAME SRC_REL_PATH OUTPUT_DIR [--LLM-active] [--experiment-id EXP] [--without-explanations] [--cycles-file FILE] [--baseline-branch NAME]" >&2
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
    --LLM-active) LLM_ACTIVE=1 ;;
    --experiment-id)
      j=$((i+1)); [[ $j -le $# ]] || err "--experiment-id needs a value"
      EXPERIMENT_ID="${!j}"; i=$((i+1))
      ;;
    --without-explanations|--without-explanation) NO_EXPLAIN=1 ;;
    --cycles-file)
      j=$((i+1)); [[ $j -le $# ]] || err "--cycles-file needs a value"
      OVERRIDE_CYCLES_FILE="${!j}"; i=$((i+1))
      ;;
    --baseline-branch)
      j=$((i+1)); [[ $j -le $# ]] || err "--baseline-branch needs a value"
      BASELINE_BRANCH="${!j}"; i=$((i+1))
      ;;
    *) err "Unknown option: $arg" ;;
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

# ---- Output dirs (baseline branch outputs) ----
ATD_DIR="$OUTPUT_DIR/ATD_identification"
QC_DIR="$OUTPUT_DIR/code_quality_checks"
mkdir -p "$ATD_DIR" "$QC_DIR"

# ---- Repo setup ----
need git
git -C "$REPO_PATH" fetch --all --prune >/dev/null 2>&1 || true

# If metrics-only and target branch doesn't exist, copy from baseline
if [[ $LLM_ACTIVE -eq 0 ]] && ! branch_exists "$BRANCH_NAME"; then
  [[ -n "$BASELINE_BRANCH" ]] || err "Branch '$BRANCH_NAME' not found and --baseline-branch not provided."
  echo "==> Target branch '$BRANCH_NAME' does not exist. Copying metrics from baseline '$BASELINE_BRANCH'."

  REPO_NAME="$(basename "$REPO_PATH")"
  RESULTS_REPO_DIR="$(dirname "$OUTPUT_DIR")"
  SRC_BASE_DIR="$RESULTS_REPO_DIR/$BASELINE_BRANCH"
  DST_BRANCH_DIR="$OUTPUT_DIR"
  mkdir -p "$DST_BRANCH_DIR"

  if [[ -d "$SRC_BASE_DIR/ATD_identification" ]]; then
    rsync -a --delete "$SRC_BASE_DIR/ATD_identification/" "$DST_BRANCH_DIR/ATD_identification/" || true
  fi
  if [[ -d "$SRC_BASE_DIR/code_quality_checks" ]]; then
    rsync -a --delete "$SRC_BASE_DIR/code_quality_checks/" "$DST_BRANCH_DIR/code_quality_checks/" || true
  fi
  echo "copied_from_baseline=$BASELINE_BRANCH" > "$DST_BRANCH_DIR/.copied_metrics_marker"
  date -Iseconds >> "$DST_BRANCH_DIR/.copied_metrics_marker"
  echo "==> Metrics copied from baseline. Skipping analysis for missing branch '$BRANCH_NAME'."
  exit 0
fi

# Normal checkout/reset for selected branch
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

# Collect cycle IDs for this repo/branch
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

  # Compute branch name and branch output base
  SAFE_CYCLE="$(sanitize_branch "$CYCLE_ID")"
  if [[ $NO_EXPLAIN -eq 1 ]]; then
    EXP_LABEL="$(sanitize_branch "${EXPERIMENT_ID}_without_explanation")"
  else
    EXP_LABEL="$(sanitize_branch "${EXPERIMENT_ID}")"
  fi
  NEW_BRANCH="$(sanitize_branch "cycle-fix-${EXP_LABEL}-${SAFE_CYCLE}")"

  # Artifacts live under the results folder for the NEW branch
  REPO_RESULTS_DIR="$(dirname "$OUTPUT_DIR")"          # results/<repo>
  BRANCH_OUT_BASE="$REPO_RESULTS_DIR/$NEW_BRANCH"      # results/<repo>/<new-branch>
  EXPLAIN_SUBDIR="$BRANCH_OUT_BASE/explain_AS"
  OPENHANDS_SUBDIR="$BRANCH_OUT_BASE/openhands"
  mkdir -p "$EXPLAIN_SUBDIR" "$OPENHANDS_SUBDIR"

  # Persist the exact cycle payload we’re targeting (even if explain fails)
  CYCLE_JSON_OUT="$BRANCH_OUT_BASE/cycle_analyzed.json"
  python3 - "$CYCLES_JSON" "$CYCLE_ID" "$CYCLE_JSON_OUT" <<'PY'
import json, sys, pathlib
mod_path = pathlib.Path(sys.argv[1])
cid = sys.argv[2]
outp = pathlib.Path(sys.argv[3])
data = json.loads(mod_path.read_text(encoding="utf-8"))
found = None
for scc in data.get("sccs", []):
    for cyc in scc.get("representative_cycles", []):
        if str(cyc.get("id")) == str(cid):
            found = cyc
            break
    if found: break
payload = {
    "cycle_id": str(cid),
    "cycle": found,  # may be None if not found
    "source_module_cycles_json": str(mod_path),
}
outp.parent.mkdir(parents=True, exist_ok=True)
outp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY

  FULL_LOG="$EXPLAIN_SUBDIR/full.log"
  FINAL_PROMPT="$EXPLAIN_SUBDIR/prompt.txt"

  # Run explain step but don't let failures kill the loop
  set +e
  if [[ $NO_EXPLAIN -eq 1 ]]; then
    python3 "$EXPLAIN_MIN_PY" \
      --repo-root "$REPO_PATH" \
      --src-root "$SRC_REL_PATH" \
      --cycle-json "$CYCLES_JSON" \
      --cycle-id "$CYCLE_ID" \
      --out-prompt "$FINAL_PROMPT" \
      2>&1 | tee "$FULL_LOG"
  else
    python3 "$EXPLAIN_PY" \
      --repo-root "$REPO_PATH" \
      --src-root "$SRC_REL_PATH" \
      --cycle-json "$CYCLES_JSON" \
      --cycle-id "$CYCLE_ID" \
      --out-prompt "$FINAL_PROMPT" \
      2>&1 | tee "$FULL_LOG"
  fi
  EXPLAIN_EXIT=$?
  set -e

  # Treat nonzero exit OR empty prompt as failure
  if [[ $EXPLAIN_EXIT -ne 0 || ! -s "$FINAL_PROMPT" ]]; then
    write_explain_status "$EXPLAIN_SUBDIR" "llm_error" "explain_step_failed_or_empty_prompt"
    echo "Explain step failed or produced empty prompt for $CYCLE_ID (exit=$EXPLAIN_EXIT). Skipping OpenHands."
    continue
  else
    write_explain_status "$EXPLAIN_SUBDIR" "ok" ""
  fi

  PROMPT_TO_USE="${PROMPT_PATH:-$FINAL_PROMPT}"

  echo "== LLM Step 2: Perform refactoring with OpenHands for $CYCLE_ID =="
  SLUG="$(derive_slug)" || err "Could not derive owner/repo from 'origin' remote."

  echo "Repo slug   : $SLUG"
  echo "Base branch : $BRANCH_NAME"
  echo "New branch  : $NEW_BRANCH"
  echo "Prompt      : $PROMPT_TO_USE"
  echo "Logs →      : $OPENHANDS_SUBDIR"

  # Run OpenHands but continue on failures (it writes its own status.json)
  set +e
  LOG_DIR="$OPENHANDS_SUBDIR" bash "$OPENHANDS_SH" "$SLUG" "$BRANCH_NAME" "$NEW_BRANCH" "$PROMPT_TO_USE"
  OH_EXIT=$?
  set -e

  if [[ $OH_EXIT -ne 0 ]]; then
    echo "OpenHands failed for $CYCLE_ID (exit=$OH_EXIT). See $OPENHANDS_SUBDIR/status.json"
  else
    echo "✅ Done $CYCLE_ID → branch: $NEW_BRANCH ; prompt: $PROMPT_TO_USE ; logs: $OPENHANDS_SUBDIR"
  fi

done

echo
echo "✅ LLM phase complete for ${#CYCLE_IDS[@]} cycle(s)."
