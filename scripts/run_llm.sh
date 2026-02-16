#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   scripts/run_llm.sh [-c pipeline.yaml] [--modes ...]
CFG="pipeline.yaml"
if [[ "${1:-}" == "-c" ]]; then
  CFG="${2:-}"; shift 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m atd_pipeline.cli llm -c "$CFG" "$@"
