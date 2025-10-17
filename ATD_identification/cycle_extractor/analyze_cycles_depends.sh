#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./analyze_cycles.sh PROJECT_PATH [OUTPUT_DIR]
#
# Edit the line below to change which dependency kinds are included.
# Default = "structural": Import, Extend, Implement, Mixin
EDGE_KINDS="Import,Extend,Implement,Mixin"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 PROJECT_PATH [OUTPUT_DIR]"
  exit 2
fi

PROJECT_PATH="${1%/}"
OUTPUT_DIR="${2:-output_ATD_identification}"


[[ -d "$PROJECT_PATH" ]] || { echo "ERROR: project path not found: $PROJECT_PATH" >&2; exit 1; }
mkdir -p "$OUTPUT_DIR"

# Force language; default to python unless caller overrides: LANGUAGE=python|java|cpp
LANGUAGE="${LANGUAGE:-python}"
case "$LANGUAGE" in
  python|java|cpp) ;;
  *) echo "ERROR: LANGUAGE must be one of: python, java, cpp (got '$LANGUAGE')" >&2; exit 2 ;;
esac

echo "Analyzing project: $PROJECT_PATH"
echo "Output dir       : $OUTPUT_DIR"
echo "Language         : $LANGUAGE"
echo "Edge kinds       : $EDGE_KINDS"

# Ensure depends-cli exists
if ! command -v depends-cli >/dev/null 2>&1; then
  echo "ERROR: 'depends-cli' not found in PATH."
  exit 1
fi
DEP_CMD=(depends-cli)

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
