#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

CASE="test_runs/cases/ok_smoke_resume_openhands_llm"
CFG="$CASE/pipeline.yaml"
RESULTS_DIR="$CASE/results"
SNAPSHOT="$CASE/snapshot.json"
PIDFILE="$CASE/fake_llm.pid"

FAKE_PORT=8012
FAKE_HOST="0.0.0.0"

stop_fake_llm() {
  if [[ -f "$PIDFILE" ]]; then
    old_pid="$(cat "$PIDFILE" || true)"
    if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
      kill "$old_pid" >/dev/null 2>&1 || true
      sleep 0.2
      kill -9 "$old_pid" >/dev/null 2>&1 || true
    fi
    rm -f "$PIDFILE"
  fi
}

start_fake_llm() {
  local extra_args=("$@")
  stop_fake_llm

  python3 -u test_runs/fake_llm_server.py \
    --host "$FAKE_HOST" \
    --port "$FAKE_PORT" \
    "${extra_args[@]}" \
    > "$CASE/fake_llm.log" 2>&1 &

  FAKE_PID=$!
  echo "$FAKE_PID" > "$PIDFILE"

  for i in {1..120}; do
    if ! kill -0 "$FAKE_PID" >/dev/null 2>&1; then
      echo "ERROR: fake LLM crashed. Log:"
      sed -n '1,200p' "$CASE/fake_llm.log" || true
      exit 1
    fi

    if curl -fsS "http://127.0.0.1:$FAKE_PORT/v1/models" -o "$CASE/models.json" >/dev/null 2>&1; then
      if python3 - <<'PY' "$CASE/models.json"
import json, sys
d = json.load(open(sys.argv[1], "r", encoding="utf-8"))
sys.exit(0 if isinstance(d, dict) and "_fake_llm" in d else 2)
PY
      then
        return 0
      fi
    fi
    sleep 0.1
  done

  echo "ERROR: fake LLM did not become ready / did not look like fake_llm_server.py"
  echo "--- fake_llm.log head ---"
  sed -n '1,160p' "$CASE/fake_llm.log" || true
  echo "--- /v1/models response ---"
  cat "$CASE/models.json" 2>/dev/null || true
  exit 1
}

cleanup() {
  echo "== Stopping fake LLM =="
  stop_fake_llm
}
trap cleanup EXIT

echo "== Cleaning old results =="
[[ "$RESULTS_DIR" == *"test_runs/cases/"* ]] || { echo "Refusing to delete unsafe path: $RESULTS_DIR"; exit 1; }
rm -rf "$RESULTS_DIR" "$SNAPSHOT"
mkdir -p "$RESULTS_DIR"

export ATD_LLM_URL="http://127.0.0.1:$FAKE_PORT/v1/chat/completions"
export ATD_OPENHANDS_NETWORK_CONTAINER="${HOSTNAME}"
export ATD_LLM_BASE_URL="http://127.0.0.1:$FAKE_PORT/v1"

echo "== Starting fake LLM (allow 1 OpenHands session, then fail forever) =="
start_fake_llm --fail_openhands_after_sessions 1 --fail_openhands_times -1 --fail_openhands_mode http_503

echo "== Running baseline =="
scripts/run_baseline.sh -c "$CFG"

echo "== Building cycles =="
scripts/build_cycles_to_analyze.sh -c "$CFG" \
  --total 2 --min-size 2 --max-size 8 \
  --out "$CASE/cycles_to_analyze.txt"

echo "== Running LLM (expect: at least one blocked-equivalent due to LLM unavailable) =="
scripts/run_llm.sh -c "$CFG" --modes explain_multiAgent

python3 test_runs/check_case.py "$CASE" --assert-has-blocked
python3 test_runs/check_case.py "$CASE" --write-snapshot "$SNAPSHOT"

echo "== Restarting fake LLM (healthy) =="
start_fake_llm

echo "== Running LLM again (should resume only missing/blocked work) =="
scripts/run_llm.sh -c "$CFG" --modes explain_multiAgent

python3 test_runs/check_case.py "$CASE" --assert-resume "$SNAPSHOT"

echo "== Running metrics =="
scripts/run_metrics.sh -c "$CFG" --modes explain_multiAgent

echo "== Final strict check =="
python3 test_runs/check_case.py "$CASE"

echo "✅ Smoke resume test finished"
