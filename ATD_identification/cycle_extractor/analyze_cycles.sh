#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./analyze_cycles.sh [PROJECT_PATH] [OUTPUT_DIR]
# Defaults:
PROJECT_PATH="${1:-../../projects_to_analyze/customTestProject}"
OUTPUT_DIR="${2:-../../output}"
PROJECT_PATH="${PROJECT_PATH%/}"

mkdir -p "$OUTPUT_DIR"

echo "Analyzing project: $PROJECT_PATH"
echo "Output dir       : $OUTPUT_DIR"

# Fixed Depends invocation (inside your Docker container)
DEP_CMD=(depends-cli)                 # always available thanks to your wrapper

# ---- Output base WITHOUT .json; Depends will append "-file.json" for file granularity ----
OUT_BASE="$OUTPUT_DIR/result-modules-sdsm"        # no ".json" here
SDSM_JSON="${OUT_BASE}-file.json"                  # expected Depends output

# ---- Step 1: run Depends (module-level SDSM) ----
echo "Running Depends (module-level)..."
"${DEP_CMD[@]}" python "$PROJECT_PATH" "$OUT_BASE" --format=json --granularity=file --detail
# Short-flag alternative:
# "${DEP_CMD[@]}" python "$PROJECT_PATH" "$OUT_BASE" -f json -g file -m

# Sanity check
if [ ! -f "$SDSM_JSON" ]; then
  echo "ERROR: Expected Depends output not found: $SDSM_JSON"
  echo "Hint: If your Depends build names it differently, adjust SDSM_JSON accordingly."
  exit 1
fi
echo "Depends output: $SDSM_JSON"

# Move to this script's folder so relative imports work
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR"

# ---- Step 2: parse SCCs + representative cycles (module-level only) ----
echo "Parsing module-level SCCs and representative cycles..."
python parse_module_cycles.py "$SDSM_JSON" "${OUTPUT_DIR}/module_cycles.json"

# ---- Step 3: compute SCC metrics (module-level only) ----
echo "Computing SCC metrics (module-level)..."
python compute_global_metrics.py "$SDSM_JSON" "${OUTPUT_DIR}/scc_metrics.json"

echo "✅ Outputs:"
echo "  - ${SDSM_JSON}              (raw Depends SDSM)"
echo "  - ${OUTPUT_DIR}/module_cycles.json  (representative cycles per SCC)"
echo "  - ${OUTPUT_DIR}/scc_metrics.json     (project-level AS metrics)"
