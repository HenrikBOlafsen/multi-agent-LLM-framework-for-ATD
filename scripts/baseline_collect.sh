#!/usr/bin/env bash
set -euo pipefail

# Contract:
#   baseline_collect.sh <repo_dir> <base_branch> <entry> <out_dir> <language>
#
# language:
#   python | csharp

if [[ $# -ne 5 ]]; then
  echo "Usage: $0 <repo_dir> <base_branch> <entry> <out_dir> <language>" >&2
  echo "  language: python | csharp" >&2
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

QUALITY_PY_SH="$ROOT/code_quality_checker/quality_collect.sh"
QUALITY_CS_SH="$ROOT/code_quality_checker/quality_collect_dotnet.sh"

[[ -d "$REPO_DIR" ]] || { echo "Missing repo dir: $REPO_DIR" >&2; exit 3; }

if [[ "$LANGUAGE" != "python" && "$LANGUAGE" != "csharp" ]]; then
  echo "ERROR: unsupported language '$LANGUAGE' (expected: python|csharp)" >&2
  exit 3
fi

if [[ "$LANGUAGE" == "csharp" ]]; then
  [[ -f "$ANALYZE_CS_SH" ]] || { echo "Missing: $ANALYZE_CS_SH" >&2; exit 3; }
  [[ -f "$QUALITY_CS_SH" ]] || { echo "Missing: $QUALITY_CS_SH" >&2; exit 3; }
else
  [[ -f "$ANALYZE_PY_SH" ]] || { echo "Missing: $ANALYZE_PY_SH" >&2; exit 3; }
  [[ -f "$QUALITY_PY_SH" ]] || { echo "Missing: $QUALITY_PY_SH" >&2; exit 3; }
fi

# Offline / local-only: no fetch, no origin reset.
git -C "$REPO_DIR" checkout -q "$BASE_BRANCH"

echo "== Baseline collect: $(basename "$REPO_DIR")@$BASE_BRANCH =="
echo "Entry    : $ENTRY"
echo "Language : $LANGUAGE"
echo "Out      : $OUT_DIR"

echo "== Step: dependency cycles =="
if [[ "$LANGUAGE" == "csharp" ]]; then
  bash "$ANALYZE_CS_SH" "$REPO_DIR" "$ENTRY" "$ATD_DIR"
else
  bash "$ANALYZE_PY_SH" "$REPO_DIR" "$ENTRY" "$ATD_DIR"
fi

echo "== Step: code quality =="
if [[ "$LANGUAGE" == "csharp" ]]; then
  OUT_DIR="$QC_DIR" bash "$QUALITY_CS_SH" "$REPO_DIR" "$BASE_BRANCH" "$ENTRY" || true
else
  OUT_DIR="$QC_DIR" bash "$QUALITY_PY_SH" "$REPO_DIR" "$BASE_BRANCH" "$ENTRY" || true
fi

SUM="$ROOT/code_quality_checker/quality_single_summary.py"
[[ -f "$SUM" ]] || SUM="$ROOT/quality_single_summary.py"
if [[ -f "$SUM" ]]; then
  python3 "$SUM" "$QC_DIR" "$QC_DIR/metrics.json" || true
fi

cat > "$OUT_DIR/meta.json" <<JSON
{
  "repo": "$(basename "$REPO_DIR")",
  "branch": "$(printf '%s' "$BASE_BRANCH")",
  "entry": "$(printf '%s' "$ENTRY")",
  "language": "$(printf '%s' "$LANGUAGE")",
  "collected_at_utc": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
}
JSON

echo "✅ Baseline collected: $OUT_DIR"
