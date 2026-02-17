# Pipeline Smoke Tests and Resume Validation

This directory contains automated smoke tests used to validate the correctness, robustness, and resume behavior of the LLM-based refactoring pipeline.

The tests focus on verifying that partial experimental progress is tracked and resumed correctly and that interrupted runs can be safely resumed after LLM failures.

These tests are used as part of the methodological validation of the experimental infrastructure.

---

## Motivation

Long-running LLM-based refactoring experiments are vulnerable to interruptions caused by:

- Terminated GPU jobs
- Dropped SSH tunnels
- Network outages
- Temporary unavailability of external LLM services
- Container crashes

Without explicit validation, such failures may corrupt experimental results, lead to duplicated work, or invalidate measurements.

The smoke tests in this directory use controlled fault injection to verify that the pipeline handles these situations correctly.

---

## Failure Model

The tests simulate realistic LLM unavailability scenarios observed in practice:

- Abrupt termination of the LLM server process
- Connection refusal during API calls
- Timeouts caused by vanished network endpoints

These failures correspond to situations where the LLM becomes unreachable without returning valid API responses.

The tests do not simulate semantic LLM errors (e.g., incorrect outputs), but focus on infrastructure-level failures.

---

## Fake LLM Server

The file `fake_llm_server.py` implements a lightweight OpenAI-compatible API used for testing.

It provides:

- `/v1/models`
- `/v1/chat/completions`

and supports configurable termination after a specified number of requests.

Key features:

- Deterministic responses
- Optional tool calls to simulate OpenHands edits
- Marker file creation to verify partial side effects
- Immediate process termination to simulate tunnel/server loss

Example usage:

```bash
python3 fake_llm_server.py --exit_after_openhands_chat 1
```

This causes the server to terminate after serving one OpenHands request.

---

## Test Structure

All test cases are located under:

```
test_runs/cases/
```

Each subdirectory represents one independent test scenario and contains:

* `run.sh` – test driver script
* `pipeline.yaml` – test configuration
* `results/` – generated artifacts
* Optional snapshot files for resume validation

Each `run.sh` script:

1. Starts the fake LLM server
2. Executes baseline and cycle selection
3. Runs the LLM pipeline
4. Injects controlled failures
5. Verifies blocked states and snapshots
6. Restarts the server
7. Resumes the experiment
8. Validates final results

All tests are fully automated.

---

## Covered Scenarios

The current test suite includes the following major scenarios.

### 1. Baseline Smoke Test

Directory:

```
ok_smoke_realish/
```

Verifies that the full pipeline executes successfully under normal conditions using the fake LLM.

Purpose:

* Validate basic infrastructure
* Verify result collection
* Ensure no unexpected crashes

---

### 2. Resume After Explanation Failure

Directory:

```
ok_smoke_resume_explain_llm/
```

Simulates LLM failure during the multi-agent explanation phase.

Verifies that:

* Interrupted explanations are detected
* Fail-fast behavior and correct resume behaviour

---

### 3. Resume After OpenHands Failure

Directory:

```
ok_smoke_resume_openhands_llm/
```

Simulates failure during OpenHands refactoring.

Verifies that:

* Blocked units are recorded
* Resume skips completed units
* Remaining work is re-executed correctly

---

### 4. Fail-Fast Behavior

Directory:

```
ok_smoke_fail_early_openhands_llm/
```

Simulates early failure during OpenHands execution.

Verifies that:

* The first blocked unit is detected
* Remaining units are skipped
* The experiment terminates cleanly
* Resume recovers only missing work

---

## Running the Tests

All tests are executed from root inside the development container.

Example:

```bash
bash test_runs/cases/ok_smoke_fail_early_openhands_llm/run.sh
```

---

## Validation Logic

Test verification is implemented in:

```
test_runs/check_case.py
```

This script validates:

* Presence of blocked units
* Resume correctness
* Snapshot consistency
* Existence of mid-run edit markers
* Final result completeness

The tests fail if any expected invariant is violated.

---

## Interpretation and Limitations

These smoke tests validate the pipeline’s resume mechanism under a defined and realistic failure model focused on LLM unavailability.

They demonstrate that:

* Partial progress is discarded correctly
* Resume avoids redundant recomputation
* Interrupted runs can be continued safely
* Final metrics remain consistent

However, the tests do not exhaustively cover all possible failure modes, such as:

* Disk corruption
* Malformed LLM responses
* Hardware failures inside containers

The tests therefore provide empirical evidence of robustness under the conditions relevant to the experimental setup used in this work, but do not constitute a formal proof of correctness.

---

## Relation to the Thesis

These smoke tests serve as infrastructure validation for the experimental results reported in the accompanying thesis.

They support the claim that:

* Observed experimental outcomes are not artifacts of interrupted runs
* Resume behavior does not bias metric measurements
* Partial failures do not invalidate completed refactorings

This increases confidence in the reliability and reproducibility of the reported results.

