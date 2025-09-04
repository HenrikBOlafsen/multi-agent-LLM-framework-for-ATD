#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./analyze_cycles.sh PROJECT_PATH [OUTPUT_DIR] [--include-tests] [--edge-profile P] [--edge-kinds CSV]
# Examples:
#   ./analyze_cycles.sh ../tinydb
#   ./analyze_cycles.sh ../tqdm out --include-tests
#   ./analyze_cycles.sh ../tqdm out --edge-profile structural
#   ./analyze_cycles.sh ../tqdm out --edge-kinds "Import,Include,Extend"

# ---- parse args ----
PROJECT_PATH=""
OUTPUT_DIR="output"
INCLUDE_TESTS=0
EDGE_PROFILE="structural"   # {import,structural,all}
EDGE_KINDS=""

usage() {
  cat <<USAGE
Usage: $0 PROJECT_PATH [OUTPUT_DIR] [--include-tests] [--edge-profile P] [--edge-kinds CSV]

Profiles:
  import      => Import, Include
  structural  => Import, Include, Extend, Implement, Mixin
  all         => Import, Include, Extend, Implement, Mixin, Call, Cast, Contain,
                 Create, Parameter, Return, Throw, Use, ImplLink

If --edge-kinds is provided, it overrides the profile.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage; exit 0
      ;;
    --include-tests)
      INCLUDE_TESTS=1; shift
      ;;
    --edge-profile)
      [[ $# -lt 2 ]] && { echo "ERROR: --edge-profile requires a value"; exit 2; }
      EDGE_PROFILE="$2"; shift 2
      ;;
    --edge-profile=*)
      EDGE_PROFILE="${1#*=}"; shift
      ;;
    --edge-kinds)
      [[ $# -lt 2 ]] && { echo "ERROR: --edge-kinds requires a value"; exit 2; }
      EDGE_KINDS="$2"; shift 2
      ;;
    --edge-kinds=*)
      EDGE_KINDS="${1#*=}"; shift
      ;;
    *)
      if [[ -z "$PROJECT_PATH" ]]; then
        PROJECT_PATH="$1"; shift
      elif [[ "$OUTPUT_DIR" == "output" ]]; then
        OUTPUT_DIR="$1"; shift
      else
        echo "ERROR: Unexpected extra argument: $1"
        usage; exit 2
      fi
      ;;
  esac
done

if [[ -z "$PROJECT_PATH" ]]; then
  usage; exit 2
fi

PROJECT_PATH="${PROJECT_PATH%/}"      # normalize trailing slash
mkdir -p "$OUTPUT_DIR"

echo "Analyzing project: $PROJECT_PATH"
echo "Output dir       : $OUTPUT_DIR"
[[ $INCLUDE_TESTS -eq 1 ]] && echo "Including tests in metrics" || echo "Excluding tests from metrics"
echo "Edge profile     : $EDGE_PROFILE"
[[ -n "$EDGE_KINDS" ]] && echo "Edge kinds (override): $EDGE_KINDS"

# Ensure depends-cli exists
if ! command -v depends-cli >/dev/null 2>&1; then
  echo "ERROR: 'depends-cli' not found in PATH. Is your Docker image set up with the wrapper?"
  exit 1
fi
DEP_CMD=(depends-cli)

# Depends output base (no .json; tool appends '-file.json')
OUT_BASE="$OUTPUT_DIR/result-modules-sdsm"
SDSM_JSON="${OUT_BASE}-file.json"

# Step 1: run Depends (module-level SDSM)
echo "Running Depends (module-level)..."
"${DEP_CMD[@]}" python "$PROJECT_PATH" "$OUT_BASE" --format=json --granularity=file --auto-include

if [ ! -f "$SDSM_JSON" ]; then
  echo "ERROR: Expected Depends output not found: $SDSM_JSON"
  exit 1
fi
echo "Depends output: $SDSM_JSON"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# Pin the repo root so node keys are stable
export REPO_ROOT="$(realpath "$PROJECT_PATH")"

# Build Python flags
PY_FLAGS=()
[[ $INCLUDE_TESTS -eq 1 ]] && PY_FLAGS+=(--include-tests)
# Prefer profile unless kinds override is provided
if [[ -n "$EDGE_KINDS" ]]; then
  PY_FLAGS+=(--edge-kinds "$EDGE_KINDS")
else
  PY_FLAGS+=(--edge-profile "$EDGE_PROFILE")
fi

# Step 2: parse SCCs + representative cycles
echo "Parsing module-level SCCs and representative cycles..."
python "$SCRIPT_DIR/parse_module_cycles.py" "$SDSM_JSON" "${OUTPUT_DIR}/module_cycles.json" "${PY_FLAGS[@]}"

# Step 3: compute SCC metrics
echo "Computing SCC metrics (module-level)..."
python "$SCRIPT_DIR/compute_global_metrics.py" "$SDSM_JSON" "${OUTPUT_DIR}/scc_metrics.json" "${PY_FLAGS[@]}"

echo "✅ Outputs:"
echo "  - ${SDSM_JSON}                        (raw Depends SDSM)"
echo "  - ${OUTPUT_DIR}/module_cycles.json    (representative cycles per SCC)"
echo "  - ${OUTPUT_DIR}/scc_metrics.json      (project-level AS metrics)"
