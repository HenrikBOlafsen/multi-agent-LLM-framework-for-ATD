#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./ATD_identification/analyze_cycles.sh <REPO_PATH> <ENTRY_SUBDIR> <OUTPUT_DIR>
#
# Produces:
#   <OUTPUT_DIR>/pydeps.json
#   <OUTPUT_DIR>/dependency_graph.json
#
# NOTE:
#   SCC extraction + cycle selection are now separate steps run later.

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <REPO_PATH> <ENTRY_SUBDIR> <OUTPUT_DIR>" >&2
  exit 2
fi

REPO_PATH="$(cd "$1" && pwd)"
ENTRY_SUBDIR="${2%/}"
OUTPUT_DIR="$(mkdir -p "$3" && cd "$3" && pwd)"

[[ -d "$REPO_PATH" ]] || { echo "ERROR: repo path not found: $REPO_PATH" >&2; exit 1; }
[[ -d "$REPO_PATH/$ENTRY_SUBDIR" ]] || { echo "ERROR: entry subdir not found: $REPO_PATH/$ENTRY_SUBDIR" >&2; exit 1; }

command -v pydeps >/dev/null 2>&1 || { echo "ERROR: pydeps not found in PATH" >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found in PATH" >&2; exit 3; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_GRAPH_PY="$SCRIPT_DIR/build_dependency_graph_pydeps.py"
[[ -f "$BUILD_GRAPH_PY" ]] || { echo "ERROR: missing: $BUILD_GRAPH_PY" >&2; exit 4; }

PYDEPS_JSON="$OUTPUT_DIR/pydeps.json"
GRAPH_JSON="$OUTPUT_DIR/dependency_graph.json"

if [[ -f "$SCRIPT_DIR/../timing.sh" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/../timing.sh"
  export TIMING_PHASE="analyze_cycles"
  export TIMING_REPO="$(basename "$REPO_PATH")"
fi

echo "== Analyze cycles (Python: graph-only) =="
echo "Repo    : $REPO_PATH"
echo "Entry   : $ENTRY_SUBDIR"
echo "Out dir : $OUTPUT_DIR"
echo

echo "== Step 1: pydeps → $PYDEPS_JSON =="
if declare -F timing_mark >/dev/null 2>&1; then timing_mark "start_pydeps"; fi

PKG_DIR="$REPO_PATH/$ENTRY_SUBDIR"
PKG_NAME="$(basename "$PKG_DIR")"
PKG_PARENT="$(dirname "$PKG_DIR")"
export PYTHONPATH="$PKG_PARENT${PYTHONPATH:+:$PYTHONPATH}"
export PACKAGE_NAME="$PKG_NAME"
export REPO_ROOT="$REPO_PATH"

pydeps "$PKG_DIR" \
  --noshow --no-output \
  --show-deps \
  --deps-output "$PYDEPS_JSON" \
  --max-bacon=0 \
  --only "$PKG_NAME"

if declare -F timing_mark >/dev/null 2>&1; then timing_mark "end_pydeps"; fi
[[ -s "$PYDEPS_JSON" ]] || { echo "ERROR: pydeps did not produce $PYDEPS_JSON" >&2; exit 10; }

echo
echo "== Step 2: build canonical dependency graph → $GRAPH_JSON =="
if declare -F timing_mark >/dev/null 2>&1; then timing_mark "start_buildDependencyGraph"; fi

python3 "$BUILD_GRAPH_PY" "$PYDEPS_JSON" \
  --repo-root "$REPO_PATH" \
  --entry "$ENTRY_SUBDIR" \
  --out "$GRAPH_JSON" \
  --language "python"

if declare -F timing_mark >/dev/null 2>&1; then timing_mark "end_buildDependencyGraph"; fi
[[ -s "$GRAPH_JSON" ]] || { echo "ERROR: graph builder did not produce $GRAPH_JSON" >&2; exit 11; }

echo
echo "✅ Done. Outputs:"
echo "  - $PYDEPS_JSON"
echo "  - $GRAPH_JSON"
