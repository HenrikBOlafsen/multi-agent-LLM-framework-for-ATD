#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

CFG="test_runs/cases/ok_smoke_minimal/pipeline.yaml"

# 1) Baseline (creates dependency_graph.json + scc_report.json + code_quality_checks)
scripts/run_baseline.sh -c "$CFG"

# 2) (Optional) If you want this case to also build catalogs automatically later:
# scripts/build_cycles_to_analyze.sh -c "$CFG" --total 10 --min-size 2 --max-size 8 --out test_runs/cases/ok_smoke_minimal/cycles_to_analyze.txt

# 3) Explain (minimal orchestrator => no LLM calls)
python3 -m atd_pipeline.cli explain -c "$CFG" --modes no_explain

# 4) Check results
python3 test_runs/check_results.py test_runs/cases/ok_smoke_minimal
echo "✅ ok_smoke_minimal passed"
