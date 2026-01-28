#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./ATD_identification/analyze_cycles.sh <REPO_PATH> <ENTRY_SUBDIR> <OUTPUT_DIR>
#
# Example:
#   ./ATD_identification/analyze_cycles.sh projects_to_analyze/kombu kombu results/kombu/main/ATD_identification
#
# Produces:
#   <OUTPUT_DIR>/pydeps.json
#   <OUTPUT_DIR>/dependency_graph.json
#   <OUTPUT_DIR>/scc_report.json

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <REPO_PATH> <ENTRY_SUBDIR> <OUTPUT_DIR>" >&2
  exit 2
fi

REPO_PATH="$(cd "$1" && pwd)"
ENTRY_SUBDIR="${2%/}"
OUTPUT_DIR="$(mkdir -p "$3" && cd "$3" && pwd)"

[[ -d "$REPO_PATH" ]] || { echo "ERROR: repo path not found: $REPO_PATH" >&2; exit 1; }
[[ -d "$REPO_PATH/$ENTRY_SUBDIR" ]] || { echo "ERROR: entry subdir not found: $REPO_PATH/$ENTRY_SUBDIR" >&2; exit 1; }

# ---- tool checks ----
command -v pydeps >/dev/null 2>&1 || { echo "ERROR: pydeps not found in PATH" >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found in PATH" >&2; exit 3; }

# ---- locations ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_GRAPH_PY="$SCRIPT_DIR/build_dependency_graph_pydeps.py"
EXTRACT_SCCS_PY="$SCRIPT_DIR/extract_sccs.py"

[[ -f "$BUILD_GRAPH_PY" ]] || { echo "ERROR: missing: $BUILD_GRAPH_PY" >&2; exit 4; }
[[ -f "$EXTRACT_SCCS_PY" ]] || { echo "ERROR: missing: $EXTRACT_SCCS_PY" >&2; exit 4; }

# ---- outputs ----
PYDEPS_JSON="$OUTPUT_DIR/pydeps.json"
GRAPH_JSON="$OUTPUT_DIR/dependency_graph.json"
SCC_REPORT_JSON="$OUTPUT_DIR/scc_report.json"

# ---- env for timing logger ----
# (optional; safe if timing.sh isn't used elsewhere)
if [[ -f "$SCRIPT_DIR/../timing.sh" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/../timing.sh"
  export TIMING_PHASE="analyze_cycles"
  export TIMING_REPO="$(basename "$REPO_PATH")"
fi

echo "== Analyze cycles =="
echo "Repo    : $REPO_PATH"
echo "Entry   : $ENTRY_SUBDIR"
echo "Out dir : $OUTPUT_DIR"
echo

# 1) pydeps
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

# 2) canonical graph
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

# 3) SCC + cycles + metrics (one pass)
echo
echo "== Step 3: SCCs + representative cycles + metrics → $SCC_REPORT_JSON =="
if declare -F timing_mark >/dev/null 2>&1; then timing_mark "start_extractSCCs"; fi

python3 "$EXTRACT_SCCS_PY" "$GRAPH_JSON" --out "$SCC_REPORT_JSON"

if declare -F timing_mark >/dev/null 2>&1; then timing_mark "end_extractSCCs"; fi
[[ -s "$SCC_REPORT_JSON" ]] || { echo "ERROR: SCC extractor did not produce $SCC_REPORT_JSON" >&2; exit 12; }

echo
echo "✅ Done. Outputs:"
echo "  - $PYDEPS_JSON"
echo "  - $GRAPH_JSON"
echo "  - $SCC_REPORT_JSON"
