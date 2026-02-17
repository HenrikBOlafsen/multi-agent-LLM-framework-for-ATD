### test_runs/cases/ok_smoke_realish/run.sh
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

CASE="test_runs/cases/ok_smoke_realish"
CFG="$CASE/pipeline.yaml"
RESULTS_DIR="$CASE/results"
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

  # Wait until it responds and identifies as fake.
  # NOTE: We probe 127.0.0.1 because both explain_AS and OpenHands are configured
  # to use 127.0.0.1 (OpenHands via ATD_OPENHANDS_NETWORK_CONTAINER namespace share).
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
[[ "$RESULTS_DIR" == *"test_runs/cases/"* ]] || {
  echo "Refusing to delete unsafe path: $RESULTS_DIR"
  exit 1
}
# Repair ownership in case previous run died mid-OpenHands (reboot, crash, ctrl-c)
docker run --rm \
  -v "$ROOT/$RESULTS_DIR:/target:rw" \
  alpine:3.20 \
  sh -lc "chown -R $(id -u):$(id -g) /target >/dev/null 2>&1 || true"
rm -rf "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR"

# explain_AS runs inside this devcontainer:
export ATD_LLM_URL="http://127.0.0.1:$FAKE_PORT/v1/chat/completions"
# OpenHands will also reach it on 127.0.0.1 because we share network namespace below:
export ATD_LLM_BASE_URL="http://127.0.0.1:$FAKE_PORT/v1"

echo "== Starting fake LLM =="
start_fake_llm

echo "== Running baseline =="
scripts/run_baseline.sh -c "$CFG"

echo "== Building cycles =="
scripts/build_cycles_to_analyze.sh -c "$CFG" \
  --total 2 --min-size 2 --max-size 8 \
  --out "$CASE/cycles_to_analyze.txt"

echo "== Running LLM =="
# Make OpenHands share the devcontainer network namespace, so 127.0.0.1 works inside OpenHands too.
export ATD_OPENHANDS_NETWORK_CONTAINER="${HOSTNAME}"
scripts/run_llm.sh -c "$CFG" --modes explain_multiAgent

echo "== Running metrics =="
scripts/run_metrics.sh -c "$CFG" --modes explain_multiAgent

echo "== Checking =="
python3 test_runs/check_case.py "$CASE"

echo "✅ Smoke test finished"
