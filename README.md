# Replication Package

This repository contains the full replication package for the experiments described in the accompanying (anonymous) paper.
It includes all scripts and Docker configurations needed to reproduce the pipeline end-to-end.

---

## Overview

All experiments are run inside a Docker container that encapsulates the environment, dependencies, and tools.
The container includes all Python packages installed via the **[uv](https://github.com/astral-sh/uv)** package manager, ensuring reproducibility.

The pipeline analyzes and refactors Python repositories using an LLM-based system.
It performs dependency graph extraction, automated LLM refactoring, and post-refactoring code quality measurements.

---

## Environment configuration

Create and fill in a `.env` file at the project root:

```bash
# LLM
LLM_MODEL=openai/Qwen/Qwen3-Coder-30B-A3B-Instruct
LLM_BASE_URL=http://host.docker.internal:8000/v1
LLM_API_KEY=placeholder

# git
GITHUB_TOKEN=
GIT_USER_NAME=
GIT_USER_EMAIL=
```

**Notes**

* `LLM_BASE_URL` should point to your hosted model endpoint, accessible from inside Docker.
* `GITHUB_TOKEN` must have push permissions to your forked repositories.
* The `GIT_USER_*` fields identify commits made by automated refactorings.

---

## Building the container

Build the development image (defined in `Dockerfile`):

```bash
docker build --target dev -t atd-dev .
```

The image installs all required dependencies via **uv**. Any additional packages specified in the Dockerfile or through `uv add ...` will automatically be included.

---

## Running inside Docker

Start the container (example for Windows Git Bash):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":"$PWD" \
  -w "$PWD" \
  --name atd-dev \
  atd-dev
```

This command mounts the project directory and Docker socket, allowing the container to run nested Docker commands (used internally by OpenHands).

---

## Preparing repositories

Fork the following repositories on GitHub and ensure you can push to them:

```
kombu
click
werkzeug
rich
jinja
celery
lark
```

Clone each fork into a folder named `projects_to_analyze/`:

```
projects_to_analyze/
 ├── kombu/
 ├── click/
 ├── werkzeug/
 ├── rich/
 ├── jinja/
 ├── celery/
 └── lark/
```

---

## Repository and cycle configuration

Two configuration files control what the pipeline analyzes:

* `repos.txt` – lists the repositories, their main branches, and source subdirectories:

  ```bash
  kombu main kombu
  click main src/click
  werkzeug main src/werkzeug
  rich master rich
  jinja main src/jinja2
  celery main celery
  lark master lark
  ```

* `cycles_to_analyze.txt` – lists which cycles to target for each repository:

  ```bash
  rich master scc_0_cycle_0
  jinja main scc_0_cycle_0
  rich master scc_0_cycle_1
  ...
  ```

If you want to analyze **different projects or cycles**, simply edit these two files before running the scripts.

---

## Running the experiments

### Baseline graph and metrics (manual, run once)

Run the non-LLM phase to compute dependency graphs and baseline metrics:

```bash
./run_all.sh projects_to_analyze/ repos.txt expA results/
```

This step builds `module_cycles.json` and code-quality metrics for each base branch.

---

### Automated LLM-based refactoring and metrics

Run the full automated pipeline (LLM + metrics):

```bash
./run_automated.sh projects_to_analyze/ repos.txt expFFF results/ cycles_to_analyze.txt
```

This performs:

* LLM refactoring *with* explanations
* LLM refactoring *without* explanations
* Metrics collection for both versions

---

### Generating research-question tables

After all experiments are finished, generate summary tables:

```bash
./run_make_rq_tables.sh \
  --results-roots results \
  --exp-ids expFFF \
  --repos-file repos.txt \
  --cycles-file cycles_to_analyze.txt \
  --outdir results
```

To combine results from multiple experiments:

```bash
./run_make_rq_tables.sh \
  --results-roots results_FFF results_GGG results_HHH results_III results_JJJ results_KKK results_LLL results_NNN \
  --exp-ids       expFFF     expGGG     expHHH     expIII     expJJJ     expKKK     expLLL     expNNN \
  --repos-file repos.txt \
  --cycles-file cycles_to_analyze.txt \
  --outdir results
```

**Important:**
The experiment IDs (e.g., `expA`, `expFFF`) must match the IDs you used in earlier runs.
They are embedded in branch names such as:

```
cycle-fix-expNNN-<cycle_id>
cycle-fix-expNNN_without_explanation-<cycle_id>
```

---

## Output structure

After running the full pipeline, your `results/` directory should look like:

```
results/
 ├── kombu/
 │   ├── main/
 │   ├── cycle-fix-expNNN-123/
 │   └── cycle-fix-expNNN_without_explanation-123/
 ├── click/
 │   └── ...
 ├── aggregated tables in results/
 └── ...
```

---

## Troubleshooting

* **Missing scripts:** Run all commands from the repository root.
* **LLM connection errors:** Check that the model endpoint in `LLM_BASE_URL` is reachable from the container.
* **No changes after refactoring:** This is expected for some cycles if the model decides no modification is necessary, or if it just hallucinates or maybe fail at using the tools from OpenHands. This is a limitation of small models.

---

## Reproducibility notes

* All dependencies are pinned and installed with **uv** inside Docker.
* All outputs (graphs, prompts, metrics, and logs) are stored under `results/`.