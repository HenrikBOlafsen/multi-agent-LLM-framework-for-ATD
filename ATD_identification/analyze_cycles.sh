#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./analyze_cycles.sh REPO_PATH SRC_SUBDIR [OUTPUT_DIR]
#
# Examples:
#   ./analyze_cycles.sh projects_to_analyze/kombu kombu
#   ./analyze_cycles.sh projects_to_analyze/click src/click
#   ./ATD_identification/cycle_extractor/analyze_cycles.sh projects_to_analyze/kombu kombu

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 REPO_PATH SRC_SUBDIR [OUTPUT_DIR]"
  exit 2
fi

REPO_PATH="${1%/}"
SRC_SUBDIR="${2%/}"
OUTPUT_DIR="${3:-output_ATD_identification}"

[[ -d "$REPO_PATH" ]] || { echo "ERROR: repo path not found: $REPO_PATH" >&2; exit 1; }

PKG_DIR="$(realpath "$REPO_PATH/$SRC_SUBDIR")"   # e.g., /work/repo/src/twisted
PKG_NAME="$(basename "$PKG_DIR")"                # e.g., twisted
PKG_PARENT="$(dirname "$PKG_DIR")"               # e.g., /work/repo/src

[[ -d "$PKG_DIR" ]] || { echo "ERROR: package dir not found: $PKG_DIR" >&2; exit 1; }
mkdir -p "$OUTPUT_DIR"

echo "Repo path   : $REPO_PATH"
echo "Package dir : $PKG_DIR"
echo "Package name: $PKG_NAME"
echo "PYTHONPATH  : $PKG_PARENT"
echo "Output dir  : $OUTPUT_DIR"

# Make sources importable if needed; not strictly required when calling pydeps on a directory
export PYTHONPATH="$PKG_PARENT${PYTHONPATH:+:$PYTHONPATH}"
# For loaders’ repo filtering
export REPO_ROOT="$(realpath "$REPO_PATH")"

# Absolute output path to avoid cwd issues
PYDEPS_JSON="$(realpath "$OUTPUT_DIR")/pydeps.json"

echo "Running pydeps on directory: $PKG_DIR"
export PACKAGE_NAME="$PKG_NAME"
pydeps "$PKG_DIR" --noshow --no-output --show-deps --deps-output "$PYDEPS_JSON" --max-bacon=0 --only "$PKG_NAME"

if [ ! -f "$PYDEPS_JSON" ]; then
  echo "ERROR: pydeps did not produce $PYDEPS_JSON"
  exit 1
fi
echo "pydeps output: $PYDEPS_JSON"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

echo "Parsing module-level SCCs and representative cycles..."
python "$SCRIPT_DIR/parse_module_cycles.py" "$PYDEPS_JSON" "${OUTPUT_DIR}/module_cycles.json"

echo "Computing SCC metrics..."
python "$SCRIPT_DIR/compute_global_metrics.py" "$PYDEPS_JSON" "${OUTPUT_DIR}/ATD_metrics.json"

echo "✅ Outputs:"
echo "  - ${PYDEPS_JSON}"
echo "  - ${OUTPUT_DIR}/module_cycles.json"
echo "  - ${OUTPUT_DIR}/ATD_metrics.json"
