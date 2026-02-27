#!/usr/bin/env bash
set -euo pipefail

PROXY_NAME="${PROXY_NAME:-atd-vllm-proxy}"

docker rm -f "$PROXY_NAME" >/dev/null 2>&1 || true
echo "[OK] Proxy stopped: $PROXY_NAME"