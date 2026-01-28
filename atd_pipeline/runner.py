from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4


def utc_timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_execution_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8]


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize_git_branch_name(candidate: str) -> str:
    candidate = candidate.strip().replace(" ", "-")
    candidate = re.sub(r"[^A-Za-z0-9._/-]+", "-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-").rstrip("/")
    return candidate


def make_refactor_branch_name(experiment_id: str, mode_id: str, cycle_id: str) -> str:
    branch_name = sanitize_git_branch_name(f"atd-{experiment_id}-{mode_id}-{cycle_id}")
    if not branch_name:
        raise ValueError("refactor branch name became empty after sanitation")
    return branch_name


def results_dir_for_branch(results_root: Path, repo_name: str, branch_name: str) -> Path:
    return results_root / repo_name / "branches" / branch_name


def run_subprocess_command(
    command: List[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> int:
    print("$ " + " ".join(command))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    process = subprocess.run(command, cwd=str(cwd) if cwd else None, env=merged)
    return int(process.returncode)


def make_llm_environment(pipeline_config) -> Dict[str, str]:
    base_url = pipeline_config.llm.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        raise ValueError(
            f"llm.base_url must end with '/v1' (got: {pipeline_config.llm.base_url}). "
            "Example: http://host.docker.internal:8012/v1"
        )
    return {
        "LLM_BASE_URL": base_url,
        "LLM_URL": f"{base_url}/chat/completions",
        "LLM_MODEL": pipeline_config.llm.model_raw,
        "LLM_API_KEY": pipeline_config.llm.api_key,
        "OPENHANDS_IMAGE": pipeline_config.openhands.image,
        "RUNTIME_IMAGE": pipeline_config.openhands.runtime_image,
        "MAX_ITERS": str(pipeline_config.openhands.max_iters),
        "COMMIT_MESSAGE": pipeline_config.openhands.commit_message,
    }


@dataclass(frozen=True)
class ExperimentUnitInfo:
    repo: str
    base_branch: str
    branch: str
    entry: Optional[str] = None
    cycle_id: Optional[str] = None
    mode_id: Optional[str] = None


def _status_filename(phase: str, rid: str) -> str:
    return f"status_{phase}_{rid}.json"


def write_phase_status_json(
    *,
    out_dir: Path,
    phase: str,
    rid: str,
    unit: ExperimentUnitInfo,
    outcome: str,  # "started" | "ok" | "failed" | "skipped"
    reason: str = "",
    returncode: Optional[int] = None,
    cmd: Optional[List[str]] = None,
    artifacts: Optional[Dict[str, str]] = None,
) -> None:
    payload: Dict[str, Any] = {
        "ts_utc": utc_timestamp_now(),
        "run_id": rid,
        "phase": phase,
        "outcome": outcome,
        "reason": reason,
        "returncode": returncode,
        "unit": {
            "repo": unit.repo,
            "base_branch": unit.base_branch,
            "branch": unit.branch,
            "entry": unit.entry,
            "cycle_id": unit.cycle_id,
            "mode_id": unit.mode_id,
        },
        "cmd": cmd,
        "artifacts": artifacts or {},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / _status_filename(phase, rid), payload)
    write_json(out_dir / f"status_{phase}_latest.json", payload)


@dataclass(frozen=True)
class ExperimentUnitRun:
    pipeline_config: Any
    repo_spec: Any
    cycle_spec: Any
    mode_spec: Any

    repo_checkout_dir: Path
    branch_results_dir: Path
    refactor_branch: str

    unit_info: ExperimentUnitInfo
    execution_id: str


# Return: ("ok"|"skipped"|"failed", reason, artifacts)
Decision = Tuple[str, str, Dict[str, str]]

ValidateInputs = Callable[[ExperimentUnitRun], Decision]
BuildCommand = Callable[[ExperimentUnitRun], List[str]]
BuildEnvironment = Callable[[ExperimentUnitRun], Optional[Dict[str, str]]]
ValidateOutputs = Callable[[ExperimentUnitRun], Decision]


def execute_phase_for_all_experiment_units(
    pipeline_config,
    experiment_units,
    *,
    phase: str,
    cwd: Path,
    validate_unit_inputs: ValidateInputs,
    build_unit_command: BuildCommand,
    build_unit_environment: BuildEnvironment,
    validate_unit_outputs: ValidateOutputs,
) -> None:
    """
    Simple semantics:
    - per-unit failures are logged and we continue
    - only Ctrl+C etc. will stop the run
    """
    for repo_spec, cycle_spec, mode_spec in experiment_units:
        repo_checkout_dir = (pipeline_config.projects_dir / repo_spec.repo).resolve()
        refactor_branch = make_refactor_branch_name(pipeline_config.experiment_id, mode_spec.id, cycle_spec.cycle_id)

        branch_results_dir = results_dir_for_branch(pipeline_config.results_root, repo_spec.repo, refactor_branch)
        branch_results_dir.mkdir(parents=True, exist_ok=True)

        unit_info = ExperimentUnitInfo(
            repo=repo_spec.repo,
            base_branch=repo_spec.base_branch,
            branch=refactor_branch,
            entry=repo_spec.entry,
            cycle_id=cycle_spec.cycle_id,
            mode_id=mode_spec.id,
        )
        rid = generate_execution_id()

        unit_run = ExperimentUnitRun(
            pipeline_config=pipeline_config,
            repo_spec=repo_spec,
            cycle_spec=cycle_spec,
            mode_spec=mode_spec,
            repo_checkout_dir=repo_checkout_dir,
            branch_results_dir=branch_results_dir,
            refactor_branch=refactor_branch,
            unit_info=unit_info,
            execution_id=rid,
        )

        # 1) inputs
        outcome, reason, artifacts = validate_unit_inputs(unit_run)
        if outcome != "ok":
            write_phase_status_json(
                out_dir=branch_results_dir,
                phase=phase,
                rid=rid,
                unit=unit_info,
                outcome=outcome,
                reason=reason,
                returncode=0 if outcome == "skipped" else 2,
                artifacts=artifacts,
            )
            continue

        # 2) command/env
        try:
            cmd = build_unit_command(unit_run)
            env = build_unit_environment(unit_run)
        except Exception as exc:
            write_phase_status_json(
                out_dir=branch_results_dir,
                phase=phase,
                rid=rid,
                unit=unit_info,
                outcome="failed",
                reason=f"build error: {exc}",
                returncode=2,
            )
            continue

        # 3) started
        write_phase_status_json(
            out_dir=branch_results_dir,
            phase=phase,
            rid=rid,
            unit=unit_info,
            outcome="started",
            cmd=cmd,
        )

        # 4) run
        rc = run_subprocess_command(cmd, cwd=cwd, env=env)
        if rc != 0:
            write_phase_status_json(
                out_dir=branch_results_dir,
                phase=phase,
                rid=rid,
                unit=unit_info,
                outcome="failed",
                reason=f"{phase} exited nonzero",
                returncode=rc,
                cmd=cmd,
            )
            continue

        # 5) outputs
        outcome, reason, artifacts = validate_unit_outputs(unit_run)
        write_phase_status_json(
            out_dir=branch_results_dir,
            phase=phase,
            rid=rid,
            unit=unit_info,
            outcome=outcome,
            reason=reason,
            returncode=0 if outcome != "failed" else 3,
            cmd=cmd,
            artifacts=artifacts,
        )
