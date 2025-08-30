#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./analyze_cycles.sh [PROJECT_PATH] [OUTPUT_DIR]
# Defaults match your earlier workflow:
#   PROJECT_PATH -> ../../projects_to_analyze/customTestProject
#   OUTPUT_DIR   -> ../../output   (repo-root/output)

PROJECT_PATH="${1:-../../projects_to_analyze/customTestProject}"
OUTPUT_DIR="${2:-../../output}"

# Normalize trailing slash
PROJECT_PATH="${PROJECT_PATH%/}"

MOD_SDSM="$OUTPUT_DIR/result-modules-sdsm.json"
FUNC_SDSM="$OUTPUT_DIR/result-functions-sdsm.json"

mkdir -p "$OUTPUT_DIR"

echo "Analyzing project: $PROJECT_PATH"
echo "Output dir       : $OUTPUT_DIR"

# ---- pick how to run Depends (prefer installed CLI; fallback to JAR) ----
if command -v depends >/dev/null 2>&1; then
  DEP_CMD=(depends)
elif command -v depends-cli >/dev/null 2>&1; then
  DEP_CMD=(depends-cli)
elif ls /opt/depends/*.jar >/dev/null 2>&1; then
  DEP_JAR="$(ls /opt/depends/*.jar | head -n1)"
  DEP_CMD=(java -Xmx8g -jar "$DEP_JAR")
else
  echo "ERROR: Depends not found in PATH or /opt/depends."
  exit 1
fi

# ---- Step 1: module-level ----
echo "Running Depends (module-level)..."
"${DEP_CMD[@]}" python "$PROJECT_PATH" "$MOD_SDSM" --format=json --granularity=file --detail
# If your Depends version only supports short flags, use the line below instead:
# "${DEP_CMD[@]}" python "$PROJECT_PATH" "$MOD_SDSM" -f json -g file -m

# ---- Step 2: function-level ----
echo "Running Depends (function-level)..."
"${DEP_CMD[@]}" python "$PROJECT_PATH" "$FUNC_SDSM" --format=json --granularity=method --detail
# Short-flag alternative:
# "${DEP_CMD[@]}" python "$PROJECT_PATH" "$FUNC_SDSM" -f json -g method -m

# Move to this script's folder so relative imports work
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR"

# ---- Step 3–6: your Python post-processing steps ----
echo "Parsing module-level cycles..."
python parse_module_cycles.py "${MOD_SDSM}-file.json" "${OUTPUT_DIR}/module_cycles.json"

echo "Parsing function-level cycles..."
python parse_function_cycles.py "${FUNC_SDSM}-method.json" "${OUTPUT_DIR}/function_cycles.json"

echo "Computing global metrics..."
python compute_global_metrics.py "${MOD_SDSM}-file.json" "${FUNC_SDSM}-method.json" "${OUTPUT_DIR}/scc_metrics.json"

echo "Merging into final cycles.json..."
python merge_cycles.py \
  "${OUTPUT_DIR}/module_cycles.json" \
  "${OUTPUT_DIR}/function_cycles.json" \
  "${OUTPUT_DIR}/scc_metrics.json" \
  "${OUTPUT_DIR}/cycles.json"

echo "✅ All cycles saved to: ${OUTPUT_DIR}/cycles.json"
