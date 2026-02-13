#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

CASE="test_runs/cases/ok_smoke_realish"
CFG="$CASE/pipeline.yaml"

RESULTS_DIR="$CASE/results"

FAKE_PORT=8012
FAKE_HOST="0.0.0.0"

echo "== Cleaning old results =="
[[ "$RESULTS_DIR" == *"test_runs/cases/"* ]] || {
  echo "Refusing to delete unsafe path: $RESULTS_DIR"
  exit 1
}
rm -rf "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR"

# explain_AS runs inside this devcontainer:
export ATD_LLM_URL="http://127.0.0.1:$FAKE_PORT/v1/chat/completions"

# OpenHands runs inside a docker container; it must reach the host running fake_llm_server.py.
# No `ip` binary here, so read default gateway from /proc/net/route (hex -> dotted).
get_docker_gateway() {
  local gw_hex
  gw_hex="$(awk '$2=="00000000" {print $3; exit}' /proc/net/route 2>/dev/null || true)"
  if [[ -n "${gw_hex:-}" && "$gw_hex" != "00000000" ]]; then
    python3 - <<'PY' "$gw_hex"
import sys, socket, struct
h = sys.argv[1].strip()
gw = socket.inet_ntoa(struct.pack("<L", int(h, 16)))
print(gw)
PY
    return 0
  fi
  # common default for docker0 on Linux
  echo "172.17.0.1"
}

DOCKER_GATEWAY="$(get_docker_gateway)"
export ATD_LLM_BASE_URL="http://$DOCKER_GATEWAY:$FAKE_PORT/v1"

echo "== Using OpenHands host gateway: $DOCKER_GATEWAY =="

echo "== Starting fake LLM =="

# Kill old server if somehow still running
pkill -f "fake_llm_server.py.*--port[[:space:]]*$FAKE_PORT" >/dev/null 2>&1 || true
pkill -f "fake_llm_server.py.*$FAKE_PORT" >/dev/null 2>&1 || true

python3 test_runs/fake_llm_server.py \
  --host "$FAKE_HOST" \
  --port "$FAKE_PORT" \
  > "$CASE/fake_llm.log" 2>&1 &

FAKE_PID=$!

cleanup() {
  echo "== Stopping fake LLM =="
  kill "$FAKE_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Wait until it responds
for i in {1..50}; do
  if curl -fsS "http://127.0.0.1:$FAKE_PORT/v1/models" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

echo "== Running baseline =="
scripts/run_baseline.sh -c "$CFG"

echo "== Building cycles =="
scripts/build_cycles_to_analyze.sh -c "$CFG" \
  --total 2 --min-size 2 --max-size 8 \
  --out "$CASE/cycles_to_analyze.txt"

echo "== Running LLM =="
# Make OpenHands share the devcontainer network namespace, so 127.0.0.1 works inside OpenHands too.
export ATD_OPENHANDS_NETWORK_CONTAINER="${HOSTNAME}"
scripts/run_llm.sh \
  -c "$CFG" \
  --modes explain_multiAgent

echo "== Running metrics =="
scripts/run_metrics.sh \
  -c "$CFG" \
  --modes explain_multiAgent

echo "== Checking =="
python3 test_runs/check_case.py "$CASE"

echo "✅ Smoke test finished"
