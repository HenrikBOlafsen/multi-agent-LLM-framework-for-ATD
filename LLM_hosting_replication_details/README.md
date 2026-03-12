# Running the Local LLM Service on Fox (vLLM + Singularity)

This repository runs a local large language model (LLM) service on the UiO Fox cluster using **vLLM inside a Singularity container**. The design prioritizes reproducibility, deterministic environments, and fast startup times on GPU nodes. Instead of dynamically installing Python packages or downloading models at runtime, the runtime environment and model weights are prepared ahead of time and stored in shared project storage. This ensures that each job runs in an identical software environment and that startup latency is minimal.

The LLM service is launched through a Slurm batch job that starts an OpenAI-compatible API server using vLLM. The model itself is loaded from a locally cached snapshot, and the container provides the full runtime stack required for GPU inference.

The paths used below correspond to the original execution environment on the UiO Fox cluster. In particular, `/cluster/work/projects/ec12/ec-henrikbo/` refers to a shared project storage directory. When reproducing the setup on another system, this path can be replaced with any writable directory that is visible from both login nodes and compute nodes.

---

## Containerized runtime environment

The runtime environment is packaged as a **Singularity (`.sif`) container** built from the official vLLM Docker image. The container includes CUDA libraries, PyTorch, and vLLM preconfigured for GPU inference. Building the container once ensures that all jobs use the exact same versions of these components.

The container was created locally from the upstream vLLM image:

```bash
singularity build vllm.sif docker://vllm/vllm-openai:v0.12.0
```

The resulting container file was copied to Fox project storage:

```
/cluster/work/projects/ec12/ec-henrikbo/containers/vllm.sif
```

Jobs then execute vLLM directly inside this container using Singularity’s GPU passthrough (`--nv`), which exposes the host NVIDIA drivers and GPUs to the containerized environment.

Using a container rather than installing dependencies inside each Slurm job has two main benefits. First, it guarantees that the Python, CUDA, PyTorch, and vLLM versions remain fixed across experiments. Second, job startup becomes significantly faster because the environment does not need to be recreated or resolved at runtime.

---

## Local model snapshot

The model used in the experiments is:

```
Qwen/Qwen3-Coder-30B-A3B-Instruct
```

Instead of referencing the Hugging Face repository at runtime, the model weights are downloaded once and stored locally in the project workspace. This produces a deterministic snapshot directory that can be reused by all jobs.

The snapshot was downloaded using the Hugging Face Hub API:

```bash
export PERSIST_ROOT="/cluster/work/projects/ec12/ec-henrikbo"
export HF_HOME="$PERSIST_ROOT/model-cache/hf"

singularity exec \
  --bind "$PERSIST_ROOT:$PERSIST_ROOT" \
  /cluster/work/projects/ec12/ec-henrikbo/containers/vllm.sif \
  python3 - <<'PY'
from huggingface_hub import snapshot_download
repo="Qwen/Qwen3-Coder-30B-A3B-Instruct"
cache_dir="/cluster/work/projects/ec12/ec-henrikbo/model-cache/hf"
snapshot_download(repo_id=repo, cache_dir=cache_dir)
PY
```

This produces a snapshot directory similar to:

```
/cluster/work/projects/ec12/ec-henrikbo/model-cache/hf/
models--Qwen--Qwen3-Coder-30B-A3B-Instruct/
snapshots/b2cff646eb4bb1d68355c01b18ae02e7cf42d120
```

The Slurm job refers directly to this snapshot path instead of the repository name. Doing so removes any dependency on remote metadata resolution and guarantees that exactly the same model revision is used for every run.

---

## Slurm job

The LLM server is started through a Slurm batch script. The script requests a single GPU, launches the container, and runs the vLLM OpenAI-compatible API server bound to localhost. The API can then be accessed through SSH port forwarding from a laptop or other client.

The script includes a confirmation gate that prevents accidental GPU allocation. After the job starts, it waits up to 15 minutes for the user to confirm the run by creating a file (`touch ~/run_now`). If the file is not created, the job exits without starting the server.

The model is served from the local snapshot with a fixed configuration:

* 32k context window
* GPU memory utilization set to 90%
* tool-calling enabled for the Qwen coder parser
* an API key required for access

A simplified example of the runtime command is:

```bash
singularity exec --nv \
  --bind /cluster/work/projects/ec12/ec-henrikbo:/cluster/work/projects/ec12/ec-henrikbo \
  /cluster/work/projects/ec12/ec-henrikbo/containers/vllm.sif \
  vllm serve MODEL_SNAPSHOT \
    --host 127.0.0.1 \
    --port 8012 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.90 \
    --served-model-name Qwen3-Coder-30B-A3B-Instruct
```

Because the model snapshot is already present locally, the server starts almost immediately after the container launches.

---

## Accessing the API

After the job starts, the server runs on the allocated GPU node and listens on a local port. Access is typically established via SSH port forwarding:

```bash
ssh -N -L 8012:127.0.0.1:8012 -J USER@fox.educloud.no USER@gpu-node
```

Once the tunnel is established, the API is available locally at:

```
http://127.0.0.1:8012/v1
```

The server exposes the standard OpenAI API interface, allowing it to be used with tools and frameworks that support OpenAI-compatible endpoints.

---

## Reusing the setup with other models

The container itself is not tied to a specific model. It provides the runtime environment required by vLLM, and most transformer models supported by vLLM can be served using the same container.

To use a different model, the main steps are to download the model snapshot and update the path referenced in the Slurm script. For example:

```python
snapshot_download(repo_id="MODEL_NAME", cache_dir="/cluster/work/.../model-cache/hf")
```

The Slurm script can then be updated to point to the new snapshot directory and optionally change the served model name or context length depending on the model’s capabilities.

A separate container is only required if the runtime environment itself must change. This may occur if a model requires a different CUDA version, a newer vLLM release, or additional Python dependencies not present in the current image. In practice, most models compatible with vLLM can run within the same container image.

---

## Caching and performance

Several runtime caches are redirected to the project workspace instead of the user home directory:

```
model-cache/vllm
model-cache/torch/inductor
model-cache/xdg
```

These caches store compiled kernels and runtime artifacts produced by PyTorch and vLLM. Keeping them in shared project storage prevents repeated compilation across jobs and improves startup time.

The result is a setup where the runtime environment, model revision, and configuration are fully pinned and reproducible. Experiments can therefore be rerun reliably without rebuilding environments or downloading dependencies at job start.