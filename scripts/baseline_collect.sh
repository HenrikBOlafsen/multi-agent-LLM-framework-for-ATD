#!/usr/bin/env bash
set -euo pipefail

# Contract:
#   baseline_collect.sh <repo_dir> <base_branch> <entry> <out_dir> <language>
#
# language:
#   python | csharp
#
# Baseline outputs (ATD):
#   ATD_identification/dependency_graph.json
#   ATD_identification/scc_report.json   (SCCs + metrics only; no representative cycles)

if [[ $# -ne 5 ]]; then
  echo "Usage: $0 <repo_dir> <base_branch> <entry> <out_dir> <language>" >&2
  exit 2
fi

REPO_DIR="$(cd "$1" && pwd)"
BASE_BRANCH="$2"
ENTRY="$3"
OUT_DIR="$(mkdir -p "$4" && cd "$4" && pwd)"
LANGUAGE="$5"

ATD_DIR="$OUT_DIR/ATD_identification"
QC_DIR="$OUT_DIR/code_quality_checks"
mkdir -p "$ATD_DIR" "$QC_DIR"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ANALYZE_PY_SH="$ROOT/ATD_identification/analyze_cycles.sh"
ANALYZE_CS_SH="$ROOT/ATD_identification/analyze_cycles_dotnet.sh"
EXTRACT_SCCS_PY="$ROOT/ATD_identification/extract_sccs.py"

QUALITY_PY_SH="$ROOT/code_quality_checker/quality_collect.sh"
QUALITY_CS_SH="$ROOT/code_quality_checker/quality_collect_csharp.sh"

SUM_PY="$ROOT/code_quality_checker/quality_single_summary.py"
SUM_CS="$ROOT/code_quality_checker/quality_single_summary_csharp.py"

[[ -d "$REPO_DIR" ]] || { echo "Missing repo dir: $REPO_DIR" >&2; exit 3; }
[[ -d "$REPO_DIR/.git" ]] || { echo "Not a git repo: $REPO_DIR" >&2; exit 3; }
[[ -f "$EXTRACT_SCCS_PY" ]] || { echo "Missing: $EXTRACT_SCCS_PY" >&2; exit 3; }

if [[ "$LANGUAGE" != "python" && "$LANGUAGE" != "csharp" ]]; then
  echo "ERROR: unsupported language '$LANGUAGE' (expected: python|csharp)" >&2
  exit 3
fi

if [[ "$LANGUAGE" == "csharp" ]]; then
  [[ -f "$ANALYZE_CS_SH" ]] || { echo "Missing: $ANALYZE_CS_SH" >&2; exit 3; }
  [[ -f "$QUALITY_CS_SH" ]] || { echo "Missing: $QUALITY_CS_SH" >&2; exit 3; }
  [[ -f "$SUM_CS" ]] || { echo "Missing: $SUM_CS" >&2; exit 3; }
else
  [[ -f "$ANALYZE_PY_SH" ]] || { echo "Missing: $ANALYZE_PY_SH" >&2; exit 3; }
  [[ -f "$QUALITY_PY_SH" ]] || { echo "Missing: $QUALITY_PY_SH" >&2; exit 3; }
  [[ -f "$SUM_PY" ]] || { echo "Missing: $SUM_PY" >&2; exit 3; }
fi

# ---- Safety guard for reset/clean ----
# We assume pipeline runs from repo root and should only mutate checkouts under it.
PIPELINE_ROOT="$ROOT"
REPO_REAL="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$REPO_DIR")"
PIPELINE_REAL="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$PIPELINE_ROOT")"

if [[ "$REPO_REAL" == "$PIPELINE_REAL" ]]; then
  echo "ERROR: refusing to reset/clean the pipeline repo itself: $REPO_DIR" >&2
  exit 4
fi

case "$REPO_REAL" in
  "$PIPELINE_REAL"/*) : ;;
  *)
    echo "ERROR: refusing to reset/clean repo outside pipeline root." >&2
    echo "  pipeline_root: $PIPELINE_REAL" >&2
    echo "  repo_dir     : $REPO_REAL" >&2
    exit 4
    ;;
esac

# Offline / local-only: no fetch, no origin reset.
git -C "$REPO_DIR" checkout -q "$BASE_BRANCH"

# Ensure the checkout is pristine (avoid cross-run contamination)
git -C "$REPO_DIR" reset --hard -q
git -C "$REPO_DIR" clean -fdx >/dev/null 2>&1 || true

echo "== Baseline collect: $(basename "$REPO_DIR")@$BASE_BRANCH =="
echo "Entry    : $ENTRY"
echo "Language : $LANGUAGE"
echo "Out      : $OUT_DIR"

echo "== Step: dependency graph extraction =="
if [[ "$LANGUAGE" == "csharp" ]]; then
  bash "$ANALYZE_CS_SH" "$REPO_DIR" "$ENTRY" "$ATD_DIR"
else
  bash "$ANALYZE_PY_SH" "$REPO_DIR" "$ENTRY" "$ATD_DIR"
fi

GRAPH_JSON="$ATD_DIR/dependency_graph.json"
SCC_REPORT="$ATD_DIR/scc_report.json"
[[ -s "$GRAPH_JSON" ]] || { echo "ERROR: missing dependency graph: $GRAPH_JSON" >&2; exit 10; }

echo "== Step: SCCs + metrics (no cycles) =="
python3 "$EXTRACT_SCCS_PY" "$GRAPH_JSON" --out "$SCC_REPORT"
[[ -s "$SCC_REPORT" ]] || { echo "ERROR: SCC extractor did not produce $SCC_REPORT" >&2; exit 11; }

echo "== Step: code quality =="
if [[ "$LANGUAGE" == "csharp" ]]; then
  OUT_DIR="$QC_DIR" bash "$QUALITY_CS_SH" "$REPO_DIR" "$BASE_BRANCH" || true
else
  OUT_DIR="$QC_DIR" bash "$QUALITY_PY_SH" "$REPO_DIR" "$BASE_BRANCH" "$ENTRY" || true
fi

echo "== Step: quality summary =="
if [[ "$LANGUAGE" == "csharp" ]]; then
  python3 "$SUM_CS" "$QC_DIR" "$QC_DIR/metrics.json" || true
else
  python3 "$SUM_PY" "$QC_DIR" "$QC_DIR/metrics.json" || true
fi

cat > "$OUT_DIR/meta.json" <<JSON
{
  "repo": "$(basename "$REPO_DIR")",
  "branch": "$(printf '%s' "$BASE_BRANCH")",
  "entry": "$(printf '%s' "$ENTRY")",
  "language": "$(printf '%s' "$LANGUAGE")",
  "collected_at_utc": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
  "artifacts": {
    "dependency_graph": "$(printf '%s' "$GRAPH_JSON")",
    "scc_report": "$(printf '%s' "$SCC_REPORT")"
  }
}
JSON

echo "✅ Baseline collected: $OUT_DIR"
