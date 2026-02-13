from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

import typer

from .config import PipelineConfig, read_repos, build_tasks
from .runner import (
    results_dir_for_branch,
    make_llm_environment,
    execute_phase_for_all_experiment_units,
    write_phase_status_json,
    write_json,
    read_json,
    generate_execution_id,
    run_subprocess_command,
    ExperimentUnitInfo,
    utc_timestamp_now,
)

app = typer.Typer(add_completion=False, no_args_is_help=True)

# Assumption: run from repo root
REPO_ROOT_DIR = Path(".").resolve()

# Hardcoded pipeline implementation paths (repo-root relative)
CYCLE_EXPLAINER_SCRIPT = REPO_ROOT_DIR / "explain_AS" / "explain_entry.py"
OPENHANDS_WRAPPER_SCRIPT = REPO_ROOT_DIR / "run_OpenHands" / "run_OpenHands.sh"
BASELINE_COLLECT_COMMAND = ["bash", str(REPO_ROOT_DIR / "scripts" / "baseline_collect.sh")]
BRANCH_METRICS_COMMAND = ["bash", str(REPO_ROOT_DIR / "scripts" / "branch_metrics_collect.sh")]


def load_pipeline_config(config_file_path: Path) -> PipelineConfig:
    pipeline_config = PipelineConfig.load(config_file_path, repo_root=REPO_ROOT_DIR)
    pipeline_config.results_root.mkdir(parents=True, exist_ok=True)
    return pipeline_config


def baseline_scc_report_path_for_repo(
    pipeline_config: PipelineConfig,
    repo_name: str,
    baseline_branch: str,
) -> Path:
    baseline_results_dir = results_dir_for_branch(pipeline_config.results_root, repo_name, baseline_branch)
    return baseline_results_dir / "ATD_identification" / "scc_report.json"


def baseline_cycle_catalog_path_for_repo(
    pipeline_config: PipelineConfig,
    repo_name: str,
    baseline_branch: str,
) -> Path:
    baseline_results_dir = results_dir_for_branch(pipeline_config.results_root, repo_name, baseline_branch)
    return baseline_results_dir / "ATD_identification" / "cycle_catalog.json"


def assert_baseline_exists_for_experiment_units(
    pipeline_config: PipelineConfig,
    experiment_units,
) -> None:
    required_pairs: Set[Tuple[str, str]] = {
        (repo_spec.repo, repo_spec.base_branch) for (repo_spec, _cycle_spec, _mode_spec) in experiment_units
    }

    missing_lines: List[str] = []
    for repo_name, baseline_branch in sorted(required_pairs):
        scc_report_path = baseline_scc_report_path_for_repo(pipeline_config, repo_name, baseline_branch)
        if not scc_report_path.exists():
            missing_lines.append(f"- {repo_name}@{baseline_branch}: missing {scc_report_path}")

    if missing_lines:
        raise typer.BadParameter(
            "Baseline results are missing for one or more repos.\n\n"
            "Run baseline first:\n"
            "  scripts/run_baseline.sh -c <your_config.yaml>\n\n"
            "Missing:\n" + "\n".join(missing_lines)
        )


def assert_cycle_catalogs_exist_for_experiment_units(
    pipeline_config: PipelineConfig,
    experiment_units,
) -> None:
    required_pairs: Set[Tuple[str, str]] = {
        (repo_spec.repo, repo_spec.base_branch) for (repo_spec, _cycle_spec, _mode_spec) in experiment_units
    }

    missing_lines: List[str] = []
    for repo_name, baseline_branch in sorted(required_pairs):
        cat_path = baseline_cycle_catalog_path_for_repo(pipeline_config, repo_name, baseline_branch)
        if not cat_path.exists():
            missing_lines.append(f"- {repo_name}@{baseline_branch}: missing {cat_path}")

    if missing_lines:
        raise typer.BadParameter(
            "Cycle catalogs are missing for one or more repos.\n\n"
            "Generate them (and cycles_to_analyze.txt) using:\n"
            "  scripts/build_cycles_to_analyze.sh -c <your_config.yaml> --max-per-size <N> --out cycles_to_analyze.txt\n\n"
            "Missing:\n" + "\n".join(missing_lines)
        )


def _load_config_and_tasks(
    config: Path,
    modes: Optional[List[str]],
    *,
    require_baseline: bool,
    require_cycle_catalogs: bool,
) -> tuple[PipelineConfig, list]:
    pipeline_config = load_pipeline_config(config)
    experiment_units = build_tasks(pipeline_config, modes)

    if require_baseline:
        assert_baseline_exists_for_experiment_units(pipeline_config, experiment_units)

    if require_cycle_catalogs:
        assert_cycle_catalogs_exist_for_experiment_units(pipeline_config, experiment_units)

    return pipeline_config, experiment_units


# ---- tiny path helpers ----

def explain_output_dir_for_unit_run(unit_run) -> Path:
    return unit_run.branch_results_dir / "explain"


def prompt_text_path_for_unit_run(unit_run) -> Path:
    return explain_output_dir_for_unit_run(unit_run) / "prompt.txt"


def openhands_output_dir_for_unit_run(unit_run) -> Path:
    return unit_run.branch_results_dir / "openhands"


def meta_output_dir_for_unit_run(unit_run) -> Path:
    return unit_run.branch_results_dir / "meta"


def scc_report_path_for_unit_run(pipeline_config: PipelineConfig, unit_run) -> Path:
    return baseline_scc_report_path_for_repo(
        pipeline_config,
        unit_run.repo_spec.repo,
        unit_run.repo_spec.base_branch,
    )


def cycle_catalog_path_for_unit_run(pipeline_config: PipelineConfig, unit_run) -> Path:
    return baseline_cycle_catalog_path_for_repo(
        pipeline_config,
        unit_run.repo_spec.repo,
        unit_run.repo_spec.base_branch,
    )


def _write_phase_meta_json(meta_dir: Path, phase: str, payload: dict) -> None:
    meta_dir.mkdir(parents=True, exist_ok=True)
    write_json(meta_dir / f"{phase}.json", payload)


# ---------------- OpenHands trajectory helpers ----------------

def _read_event_count(trajectory_path: Path) -> Optional[int]:
    """
    Simple proxy: number of trajectory events (list length).
    This counts condense events too, but that's OK as a consistent effort proxy.
    """
    try:
        if not trajectory_path.exists():
            return None
        data = read_json(trajectory_path)
        if not isinstance(data, list):
            return None
        return int(len(data))
    except Exception:
        return None


def _read_accumulated_token_usage(trajectory_path: Path) -> Dict[str, Optional[int]]:
    """
    Extract accumulated token usage from last event that has llm_metrics.accumulated_token_usage.
    Returns dict with prompt/completion/total or None values.
    """
    result: Dict[str, Optional[int]] = {
        "acc_prompt_tokens": None,
        "acc_completion_tokens": None,
        "acc_total_tokens": None,
    }

    try:
        if not trajectory_path.exists():
            return result

        data = read_json(trajectory_path)
        if not isinstance(data, list):
            return result

        for ev in reversed(data):
            if not isinstance(ev, dict):
                continue
            lm = ev.get("llm_metrics")
            if not isinstance(lm, dict):
                continue
            acc = lm.get("accumulated_token_usage")
            if not isinstance(acc, dict):
                continue

            p = acc.get("prompt_tokens")
            c = acc.get("completion_tokens")
            if p is None or c is None:
                continue

            result["acc_prompt_tokens"] = int(p)
            result["acc_completion_tokens"] = int(c)
            result["acc_total_tokens"] = int(p) + int(c)
            return result

        return result
    except Exception:
        return result

# ---------------- helper for the test-runs ----------------
def apply_test_llm_overrides(env: Dict[str, str]) -> Dict[str, str]:
    """
    Optional smoke-test overrides (do nothing unless env vars are set).
    - ATD_LLM_URL: full chat-completions endpoint used by explain_AS (e.g. http://127.0.0.1:8012/v1/chat/completions)
    - ATD_LLM_BASE_URL: base /v1 URL used by OpenHands wrapper (e.g. http://172.17.0.1:8012/v1)
    """
    llm_url = (env.get("ATD_LLM_URL") or "").strip()
    if llm_url:
        env["LLM_URL"] = llm_url

    llm_base = (env.get("ATD_LLM_BASE_URL") or "").strip()
    if llm_base:
        env["LLM_BASE_URL"] = llm_base

    return env


# ---------------- Core phase runners ----------------

def run_explain_phase(pipeline_config: PipelineConfig, experiment_units: list) -> None:
    def validate_unit_inputs(unit_run):
        scc_report_path = scc_report_path_for_unit_run(pipeline_config, unit_run)
        catalog_path = cycle_catalog_path_for_unit_run(pipeline_config, unit_run)

        missing: List[str] = []
        if not scc_report_path.exists():
            missing.append(str(scc_report_path))
        if not catalog_path.exists():
            missing.append(str(catalog_path))

        if missing:
            return (
                "failed",
                "missing baseline artifacts (run baseline + build_cycles_to_analyze): " + ", ".join(missing),
                {"missing": ", ".join(missing)},
            )
        return ("ok", "", {})

    def build_unit_command(unit_run) -> List[str]:
        repo_spec = unit_run.repo_spec
        cycle_spec = unit_run.cycle_spec
        mode_spec = unit_run.mode_spec

        scc_report_path = scc_report_path_for_unit_run(pipeline_config, unit_run)
        cycle_catalog_path = cycle_catalog_path_for_unit_run(pipeline_config, unit_run)

        explain_output_dir = explain_output_dir_for_unit_run(unit_run)
        meta_output_dir = meta_output_dir_for_unit_run(unit_run)
        explain_output_dir.mkdir(parents=True, exist_ok=True)
        meta_output_dir.mkdir(parents=True, exist_ok=True)

        prompt_output_path = prompt_text_path_for_unit_run(unit_run)

        _write_phase_meta_json(
            meta_output_dir,
            "explain",
            {
                "ts_utc": utc_timestamp_now(),
                "experiment_id": pipeline_config.experiment_id,
                "phase": "explain",
                "mode_id": mode_spec.id,
                "repo": repo_spec.repo,
                "base_branch": repo_spec.base_branch,
                "llm_branch": unit_run.refactor_branch,
                "cycle_id": cycle_spec.cycle_id,
                "entry": repo_spec.entry,
                "language": repo_spec.language,
                "explainer": str(CYCLE_EXPLAINER_SCRIPT),
                "mode_params": mode_spec.params,
                "inputs": {
                    "scc_report": str(scc_report_path),
                    "cycle_catalog": str(cycle_catalog_path),
                },
                "outputs": {
                    "prompt_txt": str(prompt_output_path),
                },
            },
        )

        return [
            "python3",
            str(CYCLE_EXPLAINER_SCRIPT),
            "--repo-root",
            str(unit_run.repo_checkout_dir),
            "--src-root",
            str(repo_spec.entry),
            "--scc-report",
            str(scc_report_path),
            "--cycle-catalog",
            str(cycle_catalog_path),
            "--cycle-id",
            cycle_spec.cycle_id,
            "--out-prompt",
            str(prompt_output_path),
        ]

    def build_unit_environment(unit_run) -> Dict[str, str]:
        environment = dict(make_llm_environment(pipeline_config))
        environment["ATD_MODE_PARAMS_JSON"] = json.dumps(unit_run.mode_spec.params)
        return apply_test_llm_overrides(environment)

    def validate_unit_outputs(unit_run):
        prompt_output_path = prompt_text_path_for_unit_run(unit_run)
        artifacts = {"prompt": str(prompt_output_path)}
        if not prompt_output_path.exists() or prompt_output_path.stat().st_size == 0:
            return ("failed", "prompt.txt missing or empty after explain", artifacts)
        return ("ok", "", artifacts)

    execute_phase_for_all_experiment_units(
        pipeline_config,
        experiment_units,
        phase="explain",
        cwd=REPO_ROOT_DIR,
        validate_unit_inputs=validate_unit_inputs,
        build_unit_command=build_unit_command,
        build_unit_environment=build_unit_environment,
        validate_unit_outputs=validate_unit_outputs,
    )


def run_openhands_phase(pipeline_config: PipelineConfig, experiment_units: list) -> None:
    def validate_unit_inputs(unit_run):
        prompt_output_path = prompt_text_path_for_unit_run(unit_run)
        if not prompt_output_path.exists() or prompt_output_path.stat().st_size == 0:
            return (
                "failed",
                f"missing explain prompt: {prompt_output_path}",
                {"prompt": str(prompt_output_path)},
            )
        return ("ok", "", {})

    def build_unit_command(unit_run) -> List[str]:
        prompt_output_path = prompt_text_path_for_unit_run(unit_run)
        openhands_output_dir = openhands_output_dir_for_unit_run(unit_run)
        openhands_output_dir.mkdir(parents=True, exist_ok=True)

        meta_output_dir = meta_output_dir_for_unit_run(unit_run)
        _write_phase_meta_json(
            meta_output_dir,
            "openhands",
            {
                "ts_utc": utc_timestamp_now(),
                "experiment_id": pipeline_config.experiment_id,
                "phase": "openhands",
                "mode_id": unit_run.mode_spec.id,
                "repo": unit_run.repo_spec.repo,
                "base_branch": unit_run.repo_spec.base_branch,
                "llm_branch": unit_run.refactor_branch,
                "cycle_id": unit_run.cycle_spec.cycle_id,
                "entry": unit_run.repo_spec.entry,
                "inputs": {
                    "prompt_txt": str(prompt_output_path),
                },
                "outputs": {
                    "openhands_dir": str(openhands_output_dir),
                },
            },
        )

        return [
            "bash",
            str(OPENHANDS_WRAPPER_SCRIPT),
            str(unit_run.repo_checkout_dir),
            unit_run.repo_spec.base_branch,
            unit_run.refactor_branch,
            str(prompt_output_path),
            str(openhands_output_dir),
        ]

    def build_unit_environment(unit_run):
        environment = dict(make_llm_environment(pipeline_config))
        return apply_test_llm_overrides(environment)

    def validate_unit_outputs(unit_run):
        out_dir = openhands_output_dir_for_unit_run(unit_run)
        status_latest = out_dir / "status_latest.json"
        traj_latest = out_dir / "trajectory_latest.json"

        artifacts: Dict[str, Any] = {
            "openhands_dir": str(out_dir),
            "openhands_status": str(status_latest),
            "trajectory": str(traj_latest),
        }

        if not status_latest.exists():
            return ("failed", "openhands did not write status_latest.json", artifacts)

        status = read_json(status_latest)
        oh_outcome = str(status.get("outcome", "")).strip()
        artifacts["openhands_outcome"] = oh_outcome

        # proxies & costs (best-effort)
        artifacts["event_count"] = _read_event_count(traj_latest)
        artifacts.update(_read_accumulated_token_usage(traj_latest))

        if oh_outcome in {"committed", "no_changes"}:
            return ("ok", f"openhands_{oh_outcome}", artifacts)

        return ("failed", f"openhands failed: {oh_outcome}", artifacts)

    execute_phase_for_all_experiment_units(
        pipeline_config,
        experiment_units,
        phase="openhands",
        cwd=REPO_ROOT_DIR,
        validate_unit_inputs=validate_unit_inputs,
        build_unit_command=build_unit_command,
        build_unit_environment=build_unit_environment,
        validate_unit_outputs=validate_unit_outputs,
    )


def run_metrics_phase(pipeline_config: PipelineConfig, experiment_units: list) -> None:
    def validate_unit_inputs(unit_run):
        out_dir = openhands_output_dir_for_unit_run(unit_run)
        status_latest = out_dir / "status_latest.json"

        if not status_latest.exists():
            return ("skipped", "skipped_missing_openhands_status", {})

        status = read_json(status_latest)
        if str(status.get("outcome", "")).strip() != "committed":
            return ("skipped", f"skipped_openhands_outcome_{status.get('outcome')}", {})

        return ("ok", "", {})

    def build_unit_command(unit_run) -> List[str]:
        repo_spec = unit_run.repo_spec

        meta_output_dir = meta_output_dir_for_unit_run(unit_run)
        _write_phase_meta_json(
            meta_output_dir,
            "metrics",
            {
                "ts_utc": utc_timestamp_now(),
                "experiment_id": pipeline_config.experiment_id,
                "phase": "metrics",
                "mode_id": unit_run.mode_spec.id,
                "repo": repo_spec.repo,
                "base_branch": repo_spec.base_branch,
                "llm_branch": unit_run.refactor_branch,
                "cycle_id": unit_run.cycle_spec.cycle_id,
                "entry": repo_spec.entry,
                "outputs": {
                    "branch_results_dir": str(unit_run.branch_results_dir),
                },
            },
        )

        return list(BRANCH_METRICS_COMMAND) + [
            str(unit_run.repo_checkout_dir),
            unit_run.refactor_branch,
            repo_spec.entry,
            str(unit_run.branch_results_dir),
            repo_spec.base_branch,
            repo_spec.language,
        ]

    def validate_unit_outputs(unit_run):
        skip_marker = unit_run.branch_results_dir / "_status_missing_branch.json"
        if skip_marker.exists():
            return ("skipped", "skipped_missing_branch", {})
        return ("ok", "", {})

    execute_phase_for_all_experiment_units(
        pipeline_config,
        experiment_units,
        phase="metrics",
        cwd=REPO_ROOT_DIR,
        validate_unit_inputs=validate_unit_inputs,
        build_unit_command=build_unit_command,
        build_unit_environment=lambda _unit_run: None,
        validate_unit_outputs=validate_unit_outputs,
    )


# -------------------------------- CLI commands --------------------------------

@app.command()
def baseline(
    config: Path = typer.Option(..., "-c", "--config", exists=True, dir_okay=False),
):
    pipeline_config = load_pipeline_config(config)
    repo_specs = read_repos(pipeline_config.repos_file)

    for repo_spec in repo_specs:
        repo_checkout_dir = (pipeline_config.projects_dir / repo_spec.repo).resolve()

        baseline_branch = repo_spec.base_branch
        branch_results_dir = results_dir_for_branch(pipeline_config.results_root, repo_spec.repo, baseline_branch)
        branch_results_dir.mkdir(parents=True, exist_ok=True)

        experiment_unit = ExperimentUnitInfo(
            repo=repo_spec.repo,
            base_branch=baseline_branch,
            branch=baseline_branch,
            entry=repo_spec.entry,
        )
        execution_id = generate_execution_id()

        command = list(BASELINE_COLLECT_COMMAND) + [
            str(repo_checkout_dir),
            baseline_branch,
            repo_spec.entry,
            str(branch_results_dir),
            repo_spec.language,
        ]

        meta_dir = branch_results_dir / "meta"
        _write_phase_meta_json(
            meta_dir,
            "baseline",
            {
                "ts_utc": utc_timestamp_now(),
                "experiment_id": pipeline_config.experiment_id,
                "phase": "baseline",
                "repo": repo_spec.repo,
                "base_branch": baseline_branch,
                "entry": repo_spec.entry,
                "outputs": {"branch_results_dir": str(branch_results_dir)},
            },
        )

        write_phase_status_json(
            out_dir=branch_results_dir,
            phase="baseline",
            rid=execution_id,
            unit=experiment_unit,
            outcome="started",
            cmd=command,
        )

        rc = run_subprocess_command(command, cwd=REPO_ROOT_DIR)
        if rc != 0:
            write_phase_status_json(
                out_dir=branch_results_dir,
                phase="baseline",
                rid=execution_id,
                unit=experiment_unit,
                outcome="failed",
                reason="baseline exited nonzero",
                returncode=rc,
                cmd=command,
            )
            continue

        write_phase_status_json(
            out_dir=branch_results_dir,
            phase="baseline",
            rid=execution_id,
            unit=experiment_unit,
            outcome="ok",
            returncode=0,
            cmd=command,
        )


@app.command()
def explain(
    config: Path = typer.Option(..., "-c", "--config", exists=True, dir_okay=False),
    modes: Optional[List[str]] = typer.Option(None, "--modes"),
):
    pipeline_config, experiment_units = _load_config_and_tasks(
        config,
        modes,
        require_baseline=True,
        require_cycle_catalogs=True,
    )
    run_explain_phase(pipeline_config, experiment_units)


@app.command()
def openhands(
    config: Path = typer.Option(..., "-c", "--config", exists=True, dir_okay=False),
    modes: Optional[List[str]] = typer.Option(None, "--modes"),
):
    pipeline_config, experiment_units = _load_config_and_tasks(
        config,
        modes,
        require_baseline=True,
        require_cycle_catalogs=True,
    )
    run_openhands_phase(pipeline_config, experiment_units)


@app.command()
def metrics(
    config: Path = typer.Option(..., "-c", "--config", exists=True, dir_okay=False),
    modes: Optional[List[str]] = typer.Option(None, "--modes"),
):
    pipeline_config, experiment_units = _load_config_and_tasks(
        config,
        modes,
        require_baseline=False,
        require_cycle_catalogs=False,
    )
    run_metrics_phase(pipeline_config, experiment_units)


@app.command()
def llm(
    config: Path = typer.Option(..., "-c", "--config", exists=True, dir_okay=False),
    modes: Optional[List[str]] = typer.Option(None, "--modes"),
):
    pipeline_config, experiment_units = _load_config_and_tasks(
        config,
        modes,
        require_baseline=True,
        require_cycle_catalogs=True,
    )
    run_explain_phase(pipeline_config, experiment_units)
    run_openhands_phase(pipeline_config, experiment_units)


if __name__ == "__main__":
    app()
