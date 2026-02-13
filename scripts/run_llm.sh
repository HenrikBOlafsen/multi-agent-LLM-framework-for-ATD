#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   scripts/run_llm.sh [-c pipeline.yaml]
# Optional env (if you want to override without editing yaml):
#   LLM_API_KEY, etc. are already handled by pipeline.yaml → CLI → env.
CFG="pipeline.yaml"
if [[ "${1:-}" == "-c" ]]; then
  CFG="${2:-}"; shift 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m atd_pipeline.cli explain -c "$CFG" "$@"
python3 -m atd_pipeline.cli openhands -c "$CFG" "$@"
