#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run_full_pipeline.sh REPO_PATH SRC_PATH [OUTPUT_DIR]
#
# Example:
#   ./run_full_pipeline.sh projects_to_analyze/kombu kombu
#
# Folders (relative to this script's location):
#   explain_AS/explain_cycle.py
#   explain_AS/select_cycle.py
#   ATD_identification/cycle_extractor/analyze_cycles.sh
#   output_ATD_identification/ (default OUTPUT_DIR)

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 REPO_PATH SRC_PATH [OUTPUT_DIR]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

REPO_PATH="${1%/}"
SRC_PATH="${2%/}"                          # package root relative to REPO_PATH (e.g., 'kombu' or 'src/werkzeug')
OUTPUT_DIR="${3:-output_ATD_identification}"

EXPLAIN_DIR="${SCRIPT_DIR}/explain_AS"
ANALYZE_SH="${SCRIPT_DIR}/ATD_identification/cycle_extractor/analyze_cycles.sh"
SELECT_PY="${EXPLAIN_DIR}/select_cycle.py"
EXPLAIN_PY="${EXPLAIN_DIR}/explain_cycle.py"

# Sanity checks
[[ -x "$ANALYZE_SH" ]] || { echo "ERROR: analyze_cycles.sh not found/executable at $ANALYZE_SH"; exit 1; }
[[ -f "$SELECT_PY" ]] || { echo "ERROR: select_cycle.py not found at $SELECT_PY"; exit 1; }
[[ -f "$EXPLAIN_PY" ]] || { echo "ERROR: explain_cycle.py not found at $EXPLAIN_PY"; exit 1; }

mkdir -p "$OUTPUT_DIR"
mkdir -p "${OUTPUT_DIR}/explanations"

echo "== Step 1: Analyze cycles =="
bash "$ANALYZE_SH" "$REPO_PATH/$SRC_PATH" "$OUTPUT_DIR"

CYCLES_JSON="${OUTPUT_DIR}/module_cycles.json"
if [[ ! -f "$CYCLES_JSON" ]]; then
  echo "ERROR: Expected cycles JSON not found: $CYCLES_JSON" >&2
  exit 1
fi

echo "== Selecting cycle: smallest representative cycle of the biggest SCC =="
CYCLE_ID="$(python3 "$SELECT_PY" "$CYCLES_JSON" || true)"

if [[ -z "${CYCLE_ID:-}" ]]; then
  echo "ERROR: Failed to determine a representative cycle from: $CYCLES_JSON" >&2
  exit 1
fi

FULL_LOG="${OUTPUT_DIR}/explanations/${CYCLE_ID}_full.txt"
FINAL_PROMPT="${OUTPUT_DIR}/explanations/${CYCLE_ID}_prompt.txt"

echo "Chosen cycle : $CYCLE_ID"
echo "Repo path    : $REPO_PATH"
echo "Src path     : $SRC_PATH"
echo "Cycles JSON  : $CYCLES_JSON"
echo "Full log     : $FULL_LOG"
echo "Final prompt : $FINAL_PROMPT"

echo "== Step 2: Explain cycle =="
# Capture *all* stdout/stderr in the full log via tee.
# The Python script itself writes the final prompt into $FINAL_PROMPT.
python3 "$EXPLAIN_PY" \
  --repo-root "$REPO_PATH" \
  --src-root "$SRC_PATH" \
  --cycle-json "$CYCLES_JSON" \
  --cycle-id "$CYCLE_ID" \
  --out-prompt "$FINAL_PROMPT" \
  2>&1 | tee "$FULL_LOG"

echo "✅ Done."
echo " - Full log    : $FULL_LOG"
echo " - Final prompt: $FINAL_PROMPT"
