### test_runs/cases/ok_smoke_fail_early_openhands_llm/run.sh
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

CASE="test_runs/cases/ok_smoke_fail_early_openhands_llm"
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

  local pid=$!
  echo "$pid" > "$PIDFILE"

  for i in {1..120}; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "ERROR: fake LLM crashed. Log:"
      sed -n '1,200p' "$CASE/fake_llm.log" || true
      exit 1
    fi

    if curl -fsS "http://127.0.0.1:$FAKE_PORT/v1/models" -o "$CASE/models.json" >/dev/null 2>&1; then
      if grep -q '"_fake_llm"[[:space:]]*:[[:space:]]*true' "$CASE/models.json"; then
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
docker run --rm \
  -v "$ROOT/$RESULTS_DIR:/target:rw" \
  alpine:3.20 \
  sh -lc "chown -R $(id -u):$(id -g) /target >/dev/null 2>&1 || true"
rm -rf "$RESULTS_DIR" "$SNAPSHOT"
mkdir -p "$RESULTS_DIR"

export ATD_LLM_URL="http://127.0.0.1:$FAKE_PORT/v1/chat/completions"
export ATD_LLM_BASE_URL="http://127.0.0.1:$FAKE_PORT/v1"
export ATD_OPENHANDS_NETWORK_CONTAINER="${HOSTNAME}"

echo "== Starting fake LLM (fail early during repo #1 OpenHands) =="
# IMPORTANT:
# - openhands_finish_tool=0 => first OpenHands response ONLY writes markers (no finish tool)
#   so OpenHands makes a second LLM call inside the same repo.
# - exit_after_openhands_chat=1 => after serving that first OpenHands response, the server dies
#   before the second OpenHands call, causing repo #1 to fail.
start_fake_llm --openhands_finish_tool 0 --exit_after_openhands_chat 1

echo "== Running baseline =="
scripts/run_baseline.sh -c "$CFG"

echo "== Building cycles =="
scripts/build_cycles_to_analyze.sh -c "$CFG" \
  --total 2 --min-size 2 --max-size 8 \
  --out "$CASE/cycles_to_analyze.txt"

echo "== Running LLM (expect: blocked during openhands; fail-fast stops remaining units) =="
set +e
scripts/run_llm.sh -c "$CFG" --modes explain_multiAgent
LLM_RC=$?
set -e
echo "LLM exit code: $LLM_RC (nonzero is OK/expected for this smoke test)"

python3 test_runs/check_case.py "$CASE" --assert-has-blocked
python3 test_runs/check_case.py "$CASE" --assert-has-midrun-edit
python3 test_runs/check_case.py "$CASE" --assert-fail-fast-phase openhands
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

echo "✅ Smoke fail-fast (openhands) test finished"
