#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./ATD_identification/analyze_cycles_dotnet.sh <REPO_PATH> <ENTRY_SUBDIR> <OUTPUT_DIR> [--sln path|--csproj path]

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <REPO_PATH> <ENTRY_SUBDIR> <OUTPUT_DIR> [--sln ...|--csproj ...]" >&2
  exit 2
fi

REPO_PATH="$(cd "$1" && pwd)"
ENTRY_SUBDIR="${2%/}"
OUTPUT_DIR="$(mkdir -p "$3" && cd "$3" && pwd)"
shift 3

[[ -d "$REPO_PATH" ]] || { echo "ERROR: repo path not found: $REPO_PATH" >&2; exit 1; }
[[ -d "$REPO_PATH/$ENTRY_SUBDIR" ]] || { echo "ERROR: entry subdir not found: $REPO_PATH/$ENTRY_SUBDIR" >&2; exit 1; }

command -v dotnet >/dev/null 2>&1 || { echo "ERROR: dotnet not found in PATH" >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found in PATH" >&2; exit 3; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTNET_DEPS_PROJ="$SCRIPT_DIR/dotnet_type_deps/DotnetTypeDeps.csproj"
EXTRACT_SCCS_PY="$SCRIPT_DIR/extract_sccs.py"

[[ -f "$DOTNET_DEPS_PROJ" ]] || { echo "ERROR: missing: $DOTNET_DEPS_PROJ" >&2; exit 4; }
[[ -f "$EXTRACT_SCCS_PY" ]] || { echo "ERROR: missing: $EXTRACT_SCCS_PY" >&2; exit 4; }

GRAPH_JSON="$OUTPUT_DIR/dependency_graph.json"
SCC_REPORT_JSON="$OUTPUT_DIR/scc_report.json"

echo "== Analyze cycles (.NET) =="
echo "Repo    : $REPO_PATH"
echo "Entry   : $ENTRY_SUBDIR"
echo "Out dir : $OUTPUT_DIR"
echo

echo "== Step 1: extract type-ref file dependencies → $GRAPH_JSON =="
# Optional but recommended: restore to reduce workspace load failures
( cd "$REPO_PATH" && dotnet restore >/dev/null 2>&1 || true )

dotnet run --project "$DOTNET_DEPS_PROJ" -- \
  --repo-root "$REPO_PATH" \
  --entry "$ENTRY_SUBDIR" \
  --out "$GRAPH_JSON" \
  "$@"

[[ -s "$GRAPH_JSON" ]] || { echo "ERROR: extractor did not produce $GRAPH_JSON" >&2; exit 11; }

echo
echo "== Step 2: SCCs + representative cycles + metrics → $SCC_REPORT_JSON =="
python3 "$EXTRACT_SCCS_PY" "$GRAPH_JSON" --out "$SCC_REPORT_JSON"

[[ -s "$SCC_REPORT_JSON" ]] || { echo "ERROR: SCC extractor did not produce $SCC_REPORT_JSON" >&2; exit 12; }

echo
echo "✅ Done. Outputs:"
echo "  - $GRAPH_JSON"
echo "  - $SCC_REPORT_JSON"
