#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./analyze_cycles.sh PROJECT_PATH [OUTPUT_DIR]
#
# Edit the line below to change which dependency kinds are included.
# Default = "structural": Import, Include, Extend, Implement, Mixin
EDGE_KINDS="Import,Include,Extend,Implement,Mixin"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 PROJECT_PATH [OUTPUT_DIR]"
  exit 2
fi

PROJECT_PATH="${1%/}"
OUTPUT_DIR="${2:-output_ATD_identification}"
mkdir -p "$OUTPUT_DIR"

echo "Analyzing project: $PROJECT_PATH"
echo "Output dir       : $OUTPUT_DIR"
echo "Edge kinds       : $EDGE_KINDS"

# Ensure depends-cli exists
if ! command -v depends-cli >/dev/null 2>&1; then
  echo "ERROR: 'depends-cli' not found in PATH."
  exit 1
fi
DEP_CMD=(depends-cli)

# --- pick language for Depends based on files present ---
detect_lang() {
  shopt -s nullglob globstar
  local p="$PROJECT_PATH"
  # Python
  if compgen -G "$p/**/*.py" > /dev/null; then echo "python"; return; fi
  # Java
  if compgen -G "$p/**/*.java" > /dev/null; then echo "java"; return; fi
  # C/C++
  if compgen -G "$p/**/*.{c,cc,cpp,cxx,h,hpp}" > /dev/null; then echo "cpp"; return; fi
  echo ""
}

LANGUAGE="$(detect_lang)"
if [[ -z "$LANGUAGE" ]]; then
  echo "ERROR: Could not detect project language (looked for .py, .java, C/C++)."
  echo "Add a detector or set LANGUAGE manually in the script."
  exit 2
fi
echo "Detected language : $LANGUAGE"

# Depends output base (no .json; tool appends '-file.json')
OUT_BASE="$OUTPUT_DIR/result-modules-sdsm"
SDSM_JSON="${OUT_BASE}-file.json"

echo "Running Depends (module-level)..."
"${DEP_CMD[@]}" "$LANGUAGE" "$PROJECT_PATH" "$OUT_BASE" --format=json --granularity=file --auto-include

if [ ! -f "$SDSM_JSON" ]; then
  echo "ERROR: Expected Depends output not found: $SDSM_JSON"
  exit 1
fi
echo "Depends output: $SDSM_JSON"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# Pin the repo root so node keys are stable
export REPO_ROOT="$(realpath "$PROJECT_PATH")"
# Pass EDGE_KINDS to Python via env (edit in this script if you want to change it)
export EDGE_KINDS

echo "Parsing module-level SCCs and representative cycles..."
python "$SCRIPT_DIR/parse_module_cycles.py" "$SDSM_JSON" "${OUTPUT_DIR}/module_cycles.json"

echo "Computing SCC metrics (module-level)..."
python "$SCRIPT_DIR/compute_global_metrics.py" "$SDSM_JSON" "${OUTPUT_DIR}/ATD_metrics.json"

echo "✅ Outputs:"
echo "  - ${SDSM_JSON}                        (raw Depends SDSM)"
echo "  - ${OUTPUT_DIR}/module_cycles.json    (representative cycles per SCC)"
echo "  - ${OUTPUT_DIR}/ATD_metrics.json      (project-level AS metrics)"
