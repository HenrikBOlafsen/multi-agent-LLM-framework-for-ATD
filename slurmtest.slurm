#!/usr/bin/env bash
#SBATCH --job-name=ollama-qwen30b
#SBATCH --account=ec12
#SBATCH --partition=accel
#SBATCH --nodelist=gpu-[7-9],gpu-14
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=%x-%j.log
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=henrbol@uio.no

set -euo pipefail
set -x
trap 'rc=$?; echo "[ERROR] Died at line $LINENO with exit $rc"; exit $rc' ERR

### -------- confirmation gate --------
READY_FILE="${READY_FILE:-$HOME/run_now}"
GRACE_MIN="${GRACE_MIN:-15}"
REQUEUE_ON_TIMEOUT="${REQUEUE_ON_TIMEOUT:-0}"

echo "[INFO] Job $SLURM_JOB_ID started on $(hostname) ($(date))."
echo "[INFO] Waiting up to ${GRACE_MIN} min for confirmation: touch ${READY_FILE}"
command -v notify-send >/dev/null 2>&1 && \
  ( DISPLAY=${DISPLAY:-} DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-} \
    notify-send "Slurm" "Job $SLURM_JOB_ID started on $(hostname). touch ${READY_FILE} to proceed." || true )

confirmed=0
for ((i=0; i<GRACE_MIN; i++)); do
  if [[ -f "$READY_FILE" ]]; then
    confirmed=1; rm -f "$READY_FILE"; break
  fi
  sleep 60
done
if [[ $confirmed -ne 1 ]]; then
  echo "[WARN] No confirmation within ${GRACE_MIN} min."
  if [[ "${REQUEUE_ON_TIMEOUT}" == "1" ]]; then scontrol requeue "$SLURM_JOB_ID"; fi
  exit 0
fi
echo "[INFO] Confirmation received — proceeding."

### -------------------- Ollama setup --------------------
PORT="${PORT:-11434}"                          # change if you like
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3-coder:30b}"# e.g. qwen3-coder:30b:Q4_K_M
INFO_DIR="$HOME/.fox-llm"; mkdir -p "$INFO_DIR"
INFO_FILE="$INFO_DIR/ollama_${SLURM_JOB_ID}.info"

# Persistent caches (adjust project root if needed)
PERSIST_ROOT="/cluster/work/projects/ec12/ec-henrikbo"
mkdir -p "$PERSIST_ROOT"/{ollama,xdg,cuda}
export OLLAMA_MODELS="$PERSIST_ROOT/ollama"    # where model blobs go
export XDG_CACHE_HOME="$PERSIST_ROOT/xdg"
export CUDA_CACHE_PATH="$PERSIST_ROOT/cuda"

# GPU probe (optional hints)
NGPU=$(nvidia-smi -L | wc -l || echo 1)
VRAM0=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1 || echo 0)
echo "[Ollama] GPUs=$NGPU  VRAM0=${VRAM0}MiB"

# Multi-GPU offload (Ollama can shard across multiple GPUs if you request more)
export OLLAMA_NUM_GPU="${OLLAMA_NUM_GPU:-1}"   # set >1 only if --gres=gpu:N
# Optional: enable flash-attention if supported by your build
export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"

# Bind Ollama to localhost:$PORT (OpenAI-compatible API at /v1)
export OLLAMA_HOST="127.0.0.1:${PORT}"

echo
echo "================ Ollama ================"
echo "Job ID:     ${SLURM_JOB_ID:-N/A}"
echo "Node:       $(hostname)"
echo "Model:      ${OLLAMA_MODEL}"
echo "Port:       ${PORT}  (OpenAI base: http://127.0.0.1:${PORT}/v1)"
echo "Models dir: ${OLLAMA_MODELS}"
echo "========================================"

{
  echo "JOB_ID=${SLURM_JOB_ID}"
  echo "NODE=$(hostname)"
  echo "PORT=${PORT}"
  echo "MODEL=${OLLAMA_MODEL}"
} > "$INFO_FILE"

# Ensure ~/.local/bin on PATH (for user install)
export PATH="$HOME/.local/bin:$PATH"

# Install Ollama if missing (user-space)
if ! command -v ollama >/dev/null 2>&1; then
  echo "[Install] Ollama not found; installing to \$HOME/.local ..."
  # Minimal user-space install (no sudo). Adjust if your site blocks curl.
  mkdir -p "$HOME/.local/bin"
  curl -L https://ollama.com/download/ollama-linux-amd64 -o "$HOME/.local/bin/ollama"
  chmod +x "$HOME/.local/bin/ollama"
fi
ollama --version || true

# Start server in the background
echo "[Ollama] Starting server on ${OLLAMA_HOST} ..."
( nohup ollama serve > "ollama_${SLURM_JOB_ID}.serve.log" 2>&1 & echo $! > "ollama_${SLURM_JOB_ID}.pid" )

# Wait until it responds
echo "[Ollama] Waiting for server to become ready ..."
for i in {1..60}; do
  if curl -s "http://${OLLAMA_HOST}/api/version" >/dev/null; then break; fi
  sleep 2
done

# Pull model (this downloads to $OLLAMA_MODELS)
echo "[Ollama] Pulling model: ${OLLAMA_MODEL}"
ollama pull "${OLLAMA_MODEL}"

echo
echo "[Connect from your laptop]:"
echo "ssh -N -L ${PORT}:127.0.0.1:${PORT} -J \$USER@fox.educloud.no \$USER@$(hostname)"
echo
echo "[Client config examples]"
echo "OpenAI base URL:  http://127.0.0.1:${PORT}/v1"
echo "Model name:       ${OLLAMA_MODEL}"
echo
echo "curl -s http://127.0.0.1:${PORT}/v1/models | jq ."
echo

# Keep the allocation alive while serving; tail logs
tail -f "ollama_${SLURM_JOB_ID}.serve.log"
