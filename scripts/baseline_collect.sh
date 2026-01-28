#!/usr/bin/env bash
set -euo pipefail

# Contract:
#   baseline_collect.sh <repo_dir> <base_branch> <entry> <out_dir>

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <repo_dir> <base_branch> <entry> <out_dir>" >&2
  exit 2
fi

REPO_DIR="$(cd "$1" && pwd)"
BASE_BRANCH="$2"
ENTRY="$3"
OUT_DIR="$(mkdir -p "$4" && cd "$4" && pwd)"

ATD_DIR="$OUT_DIR/ATD_identification"
QC_DIR="$OUT_DIR/code_quality_checks"
mkdir -p "$ATD_DIR" "$QC_DIR"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANALYZE_SH="$ROOT/ATD_identification/analyze_cycles.sh"
QUALITY_SH="$ROOT/code_quality_checker/quality_collect.sh"

[[ -f "$ANALYZE_SH" ]] || { echo "Missing: $ANALYZE_SH" >&2; exit 3; }
[[ -f "$QUALITY_SH" ]] || { echo "Missing: $QUALITY_SH" >&2; exit 3; }

# Offline / local-only: no fetch, no origin reset.
git -C "$REPO_DIR" checkout -q "$BASE_BRANCH"

echo "== Baseline collect: $(basename "$REPO_DIR")@$BASE_BRANCH =="
echo "Entry: $ENTRY"
echo "Out  : $OUT_DIR"

echo "== Step: dependency cycles =="
bash "$ANALYZE_SH" "$REPO_DIR" "$ENTRY" "$ATD_DIR"

echo "== Step: code quality =="
OUT_DIR="$QC_DIR" bash "$QUALITY_SH" "$REPO_DIR" "$BASE_BRANCH" "$ENTRY" || true

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
  "collected_at_utc": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
}
JSON

echo "✅ Baseline collected: $OUT_DIR"
