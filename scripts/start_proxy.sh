#!/usr/bin/env bash
set -euo pipefail

PROXY_NAME="${PROXY_NAME:-atd-vllm-proxy}"
PROXY_PORT="${PROXY_PORT:-8013}"
PROXY_IMAGE="${PROXY_IMAGE:-python:3.11-slim}"

# Upstream is your Windows->Fox SSH tunnel endpoint from the *host* perspective.
# (Your atd-dev container resolves host.docker.internal via --add-host host-gateway.)
UPSTREAM="${UPSTREAM:-http://host.docker.internal:8012}"

ROOT_IN_REPO="/workspace"
LOGDIR_IN_REPO="${LOGDIR_IN_REPO:-vllm_proxy_logs}"

if [[ -z "${HOST_PWD:-}" ]]; then
  echo "[ERROR] HOST_PWD is not set. You must pass -e HOST_PWD=\$(pwd) when launching atd-dev."
  exit 2
fi

# Stop any existing container with same name
docker rm -f "$PROXY_NAME" >/dev/null 2>&1 || true

echo "[INFO] Starting proxy container '$PROXY_NAME' on port ${PROXY_PORT} -> ${UPSTREAM}"
echo "[INFO] Mounting host repo path: ${HOST_PWD} -> ${ROOT_IN_REPO}"

# Start proxy as a sibling container on the host docker daemon
docker run -d --rm \
  --name "$PROXY_NAME" \
  --add-host host.docker.internal:host-gateway \
  -p "${PROXY_PORT}:8013" \
  -v "${HOST_PWD}:${ROOT_IN_REPO}:rw" \
  -w "${ROOT_IN_REPO}" \
  -e "UPSTREAM=${UPSTREAM}" \
  -e "LOGDIR=${ROOT_IN_REPO}/${LOGDIR_IN_REPO}" \
  "$PROXY_IMAGE" \
  sh -lc "pip -q install requests && python ${ROOT_IN_REPO}/vllm_proxy.py" >/dev/null

# Verify container exists and is running
if ! docker ps --format '{{.Names}}' | grep -qx "$PROXY_NAME"; then
  echo "[ERROR] Proxy container did not start."
  echo "[INFO] docker ps -a:"
  docker ps -a --format "table {{.Names}}\t{{.Status}}" | head -n 50 || true
  echo "[INFO] docker logs ${PROXY_NAME}:"
  docker logs --tail 200 "$PROXY_NAME" || true
  exit 3
fi

# Verify /v1/models works (requires Authorization header because vLLM has --api-key)
echo "[INFO] Verifying proxy is reachable (expects 401 without auth, 200 with auth)."

set +e
curl -fsS --max-time 2 "http://host.docker.internal:${PROXY_PORT}/v1/models" >/dev/null 2>&1
NOAUTH_RC=$?
set -e

if [[ "$NOAUTH_RC" -eq 0 ]]; then
  echo "[WARN] Proxy responded without auth; is vLLM api-key disabled upstream?"
else
  echo "[OK] Proxy responds (no-auth call not allowed, as expected)."
fi

echo "[OK] Proxy started: ${PROXY_NAME}"
echo "     From atd-dev container:  http://host.docker.internal:${PROXY_PORT}/v1"
echo "     From host (often):       http://127.0.0.1:${PROXY_PORT}/v1"
echo "     Logs dir in repo:        ${LOGDIR_IN_REPO}/"
echo
echo "Test (from atd-dev):"
echo "  curl -fsS -H 'Authorization: Bearer placeholder' http://host.docker.internal:${PROXY_PORT}/v1/models"