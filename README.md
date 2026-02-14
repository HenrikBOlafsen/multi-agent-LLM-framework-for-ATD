# Automated LLM-Based Architectural Refactoring Pipeline

This repository contains the experimental pipeline used to analyze and refactor architectural dependency cycles in real-world open-source software projects using LLMs.

The pipeline automatically extracts dependency graphs, identifies strongly connected components, selects architectural cycles, produces an explanation of the cycles using a multi-agent LLM approach, applies LLM-based refactoring using OpenHands, and evaluates the results using architectural and code-quality metrics. All experiments are executed inside Docker and are designed to run fully offline with respect to version control.

The repository is intended as a replication package for a master’s thesis and related research work, and for anyone who wish to run similar experiments.

---

## Platform

The pipeline was developed and executed on a Windows host system using an Ubuntu environment (WSL) and Docker. All experiments were run inside Linux containers, with the project repository stored inside the Linux filesystem.

Compatibility with other platforms has not been tested.

---

## Overview of the Pipeline

Each experiment consists of four main phases.

First, the baseline phase extracts module-level dependency graphs and computes strongly connected components and baseline metrics for each project.

Second, a cycle selection phase builds a catalog of architectural dependency cycles and selects a subset for analysis.

Third, a multi-agent LLM team tries to explain the cycle.

Fourth, the refactoring phase uses OpenHands and a configured LLM endpoint to attempt automated refactoring using the explanation generated in the last step. For each selected cycle, a local Git branch is created, OpenHands is executed, and all file changes are committed locally.

Finally, a metrics phase recomputes architectural and code-quality metrics on the refactored code.

All configuration is controlled through a YAML file.

---

## Configuration

Experiments are configured using a YAML file located in `configs/`, for example `configs/pipeline.yaml`.

This file specifies the locations of the analyzed repositories, the repository list, the cycle list, the results directory, the experiment identifier, and the parameters used for OpenHands and the LLM.

An example configuration is shown below:

```yaml
projects_dir: projects_to_analyze
repos_file: repos.txt
cycles_file: cycles_to_analyze.txt
results_root: results
experiment_id: expA

llm:
  base_url: "http://host.docker.internal:8012/v1"
  api_key: "placeholder"
  model_raw: "/path/to/model"

openhands:
  image: "docker.all-hands.dev/all-hands-ai/openhands:0.59"
  runtime_image: "docker.all-hands.dev/all-hands-ai/runtime:0.59-nikolaik"
  max_iters: 100
  commit_message: "Refactor: break dependency cycle"

modes:
  - id: no_explain
    params:
      orchestrator: minimal

  - id: explain_multiAgent1
    params:
      orchestrator: v1_four_agents
      refactor_prompt_variant: default

  - id: explain_multiAgent2
    params:
      orchestrator: agent_tree
      refactor_prompt_variant: vague
```

Users must provide their own OpenAI-compatible LLM endpoint. The endpoint must be reachable from inside the Docker container and support the `/v1/chat/completions` API.

No GitHub credentials are required, as all experiments operate on local branches only.

---

## Repository Preparation

All subject systems must be cloned manually into the directory specified by `projects_dir` (by default `projects_to_analyze/`). The pipeline does not automatically download repositories.

Each repository must correspond to an entry in `repos.txt`, which specifies the repository name, base branch, entry directory, and implementation language.

The cycle list used for refactoring is stored in `cycles_to_analyze.txt`. This file is generated automatically using the provided scripts and should not normally be edited manually, unless you want specific cycles to be excluded/included.

---

## Building and Running the Container

The Docker image is built using the provided `Dockerfile`:

```bash
docker build --target dev -t atd-dev .
```

All experiments are executed inside this container.

The container is started using:

```bash
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)

docker run --rm -it \
  --add-host=host.docker.internal:host-gateway \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)":/workspace \
  -w /workspace \
  --name atd-dev \
  --user "$(id -u):$(id -g)" \
  --group-add "$DOCKER_GID" \
  -e HOST_PWD="$(pwd)" \
  atd-dev
```

This configuration allows OpenHands to launch nested containers and ensures correct file ownership.

---

## Running Experiments

Baseline analysis is performed using:

```bash
scripts/run_baseline.sh -c configs/pipeline.yaml
```

Cycle selection is performed using:

```bash
scripts/build_cycles_to_analyze.sh -c configs/pipeline.yaml \
  --total 100 \
  --min-size 2 \
  --max-size 8 \
  --out cycles_to_analyze.txt
```

LLM-based refactoring is performed using:

```bash
scripts/run_llm.sh -c configs/pipeline.yaml --modes explain_multiAgent1 --modes explain_multiAgent2
```

Post-refactoring metrics are collected using:

```bash
scripts/run_metrics.sh -c configs/pipeline.yaml --modes explain_multiAgent1 --modes explain_multiAgent2
```

---

## Local Branch and Commit Policy

Each OpenHands run operates on a temporary Git worktree and a dedicated local branch. All changes are committed locally and never pushed to remote repositories.

No GitHub authentication is required, and running large-scale experiments does not affect remote repositories.

For each run, the complete patch produced by the LLM is stored in the results directory. After completion, the temporary worktree is removed to prevent accidental reuse.

---

## Results Structure

All experimental outputs are stored under the directory specified by `results_root` in the configuration file.

For each repository, branch, and experimental mode, the results include:

* Explanation prompt + usage + transcript
* OpenHands execution logs and trajectories
* Git patch files containing all code changes
* Dependency graphs and SCC reports
* Test results and code-quality metrics
* Status and metadata files

These artifacts make it possible to inspect, reproduce, and audit each individual refactoring attempt.

---

## Smoke Testing with a Fake LLM

For testing and validation, the repository includes a fake OpenAI-compatible server that produces deterministic edits and immediate termination.

This mode can be used to verify the correctness of the pipeline infrastructure, Git handling, and metrics collection without relying on a real LLM endpoint.

---

## Reproducibility

All experiments are executed inside Docker with pinned tool versions. The pipeline stores complete logs, trajectories, diffs, and metrics for each run.

No remote Git operations are performed, and all experimental artifacts are preserved locally. This design enables full reproducibility and post-hoc inspection of all refactoring attempts.

