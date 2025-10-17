#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./analyze_cycles.sh REPO_PATH SRC_SUBDIR [OUTPUT_DIR]
#
# Examples:
#   ./analyze_cycles.sh projects_to_analyze/kombu kombu
#   ./analyze_cycles.sh projects_to_analyze/click src/click
#   ./ATD_identification/cycle_extractor/analyze_cycles.sh projects_to_analyze/kombu kombu
#
# Outputs:
#   output_ATD_identification/pydeps.json
#   output_ATD_identification/module_cycles.json
#   output_ATD_identification/ATD_metrics.json

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 REPO_PATH SRC_SUBDIR [OUTPUT_DIR]"
  exit 2
fi

REPO_PATH="${1%/}"
SRC_SUBDIR="${2%/}"
OUTPUT_DIR="${3:-output_ATD_identification}"

[[ -d "$REPO_PATH" ]] || { echo "ERROR: repo path not found: $REPO_PATH" >&2; exit 1; }

PKG_DIR="$(realpath "$REPO_PATH/$SRC_SUBDIR")"   # e.g., /work/repo/src/click
PKG_NAME="$(basename "$PKG_DIR")"                # e.g., click
PKG_PARENT="$(dirname "$PKG_DIR")"               # e.g., /work/repo/src

[[ -d "$PKG_DIR" ]] || { echo "ERROR: package dir not found: $PKG_DIR" >&2; exit 1; }
mkdir -p "$OUTPUT_DIR"

echo "Repo path   : $REPO_PATH"
echo "Package dir : $PKG_DIR"
echo "Package name: $PKG_NAME"
echo "PYTHONPATH  : $PKG_PARENT"
echo "Output dir  : $OUTPUT_DIR"

# Make sources importable for pydeps/importlib
export PYTHONPATH="$PKG_PARENT${PYTHONPATH:+:$PYTHONPATH}"
export REPO_ROOT="$(realpath "$PKG_PARENT")"


# Sanity check: package is importable
python - <<PY || { echo "ERROR: cannot import $PKG_NAME with PYTHONPATH=$PYTHONPATH" >&2; exit 2; }
import importlib
m = importlib.import_module("${PKG_NAME}")
print(getattr(m, "__file__", "<no __file__>"))
PY

# Absolute output path
PYDEPS_JSON="$(realpath "$OUTPUT_DIR")/pydeps.json"

echo "Running pydeps (scoped to package prefix): $PKG_DIR  --only $PKG_NAME"
pydeps "$PKG_DIR" \
  --noshow --no-output --show-deps \
  --only "$PKG_NAME" \
  --deps-output "$PYDEPS_JSON"

if [ ! -f "$PYDEPS_JSON" ]; then
  echo "ERROR: pydeps did not produce $PYDEPS_JSON"
  exit 1
fi
echo "pydeps output: $PYDEPS_JSON"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# 2) Cycles JSON (representative cycles per SCC)
python "$SCRIPT_DIR/parse_module_cycles.py" "$PYDEPS_JSON" "${OUTPUT_DIR}/module_cycles.json"

# 3) Global SCC metrics
python "$SCRIPT_DIR/compute_global_metrics.py" "$PYDEPS_JSON" "${OUTPUT_DIR}/ATD_metrics.json"

echo "✅ Outputs:"
echo "  - ${PYDEPS_JSON}"
echo "  - ${OUTPUT_DIR}/module_cycles.json"
echo "  - ${OUTPUT_DIR}/ATD_metrics.json"

