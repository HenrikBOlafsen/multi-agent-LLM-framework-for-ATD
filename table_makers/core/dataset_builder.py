from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from core.analysis_plan import AnalysisPlan, PlannedMode, load_analysis_plan
from core.io_utils import path_exists, read_json, write_dataframe_csv
from core.paths import build_run_artifact_paths
from core.pipeline_inputs import load_pipeline_inputs, read_cycles_file, read_repos_file
from metrics.metrics_behavior import behavior_preserved_from_metrics
from metrics.metrics_diff import compute_diff_metrics
from metrics.metrics_prompt import compute_explanation_length
from metrics.metrics_structure import compute_structural_metrics


def _iter_all_modes(plan: AnalysisPlan) -> List[PlannedMode]:
    return list(plan.modes.values())


def _read_openhands_outcome(status_path: Path) -> str:
    if not path_exists(status_path):
        return ""
    try:
        data = read_json(status_path)
    except Exception:
        return ""
    return str(data.get("outcome", "")).strip()


def _is_no_change_run(openhands_outcome: str) -> bool:
    return openhands_outcome == "no_changes"


def _find_cycle_record_recursive(obj: Any, cycle_id: str) -> Optional[Dict[str, Any]]:
    if isinstance(obj, dict):
        if obj.get("id") == cycle_id:
            return obj

        for value in obj.values():
            found = _find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    elif isinstance(obj, list):
        for value in obj:
            found = _find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    return None


def _read_cycle_size_from_catalog(cycle_catalog_path: Path, cycle_id: str) -> Optional[int]:
    if not path_exists(cycle_catalog_path):
        return None

    try:
        catalog = read_json(cycle_catalog_path)
    except Exception:
        return None

    record = _find_cycle_record_recursive(catalog, cycle_id)
    if record is None:
        return None

    length = record.get("length")

    if isinstance(length, int):
        return length

    if isinstance(length, float) and length.is_integer():
        return int(length)

    return None


def iter_planned_runs(
    config_path: Path,
    analysis_plan_path: Path,
) -> List[Dict[str, object]]:
    pipeline_inputs = load_pipeline_inputs(config_path)
    plan = load_analysis_plan(analysis_plan_path)

    repo_specs = {r.repo: r for r in read_repos_file(pipeline_inputs.repos_file)}
    cycle_specs = read_cycles_file(pipeline_inputs.cycles_file)

    rows: List[Dict[str, object]] = []

    for mode in _iter_all_modes(plan):
        for experiment_id in mode.experiments:
            for cycle in cycle_specs:
                repo_spec = repo_specs.get(cycle.repo)

                if repo_spec is None:
                    raise ValueError(
                        f"cycles file references unknown repo {cycle.repo!r} "
                        "not found in repos file"
                    )

                if repo_spec.base_branch != cycle.base_branch:
                    raise ValueError(
                        f"Base branch mismatch for repo {cycle.repo}: "
                        f"repos file has {repo_spec.base_branch!r}, "
                        f"cycles file has {cycle.base_branch!r}"
                    )

                artifact_paths = build_run_artifact_paths(
                    results_root=pipeline_inputs.results_root,
                    repo=cycle.repo,
                    base_branch=cycle.base_branch,
                    experiment_id=experiment_id,
                    mode_id=mode.id,
                    cycle_id=cycle.cycle_id,
                )

                rows.append(
                    {
                        "experiment_id": experiment_id,
                        "mode_id": mode.id,
                        "mode_label": mode.label,
                        "repo": cycle.repo,
                        "base_branch": cycle.base_branch,
                        "cycle_id": cycle.cycle_id,
                        "language": repo_spec.language,
                        "entry": repo_spec.entry,
                        "branch_name": artifact_paths.branch_name,
                        "branch_results_dir": str(artifact_paths.branch_results_dir),
                        "baseline_results_dir": str(artifact_paths.baseline_results_dir),
                        "baseline_metrics_path": str(artifact_paths.baseline_metrics_path),
                        "post_metrics_path": str(artifact_paths.post_metrics_path),
                        "baseline_graph_path": str(artifact_paths.baseline_graph_path),
                        "post_graph_path": str(artifact_paths.post_graph_path),
                        "baseline_scc_report_path": str(
                            artifact_paths.baseline_scc_report_path
                        ),
                        "post_scc_report_path": str(artifact_paths.post_scc_report_path),
                        "baseline_cycle_catalog_path": str(
                            artifact_paths.baseline_cycle_catalog_path
                        ),
                        "openhands_status_path": str(artifact_paths.openhands_status_path),
                        "explain_prompt_path": str(artifact_paths.explain_prompt_path),
                        "diff_patch_path": str(artifact_paths.diff_patch_path),
                    }
                )

    return rows


def validate_all_planned_runs_exist(planned_rows: List[Dict[str, object]]) -> None:
    missing: List[str] = []

    for row in planned_rows:
        branch_results_dir = Path(str(row["branch_results_dir"]))
        if not branch_results_dir.exists():
            missing.append(
                f"- mode={row['mode_id']} experiment={row['experiment_id']} "
                f"repo={row['repo']} cycle={row['cycle_id']} "
                f"missing_results_dir={branch_results_dir}"
            )

    if missing:
        preview = "\n".join(missing[:50])
        extra = f"\n... and {len(missing) - 50} more" if len(missing) > 50 else ""
        raise FileNotFoundError(
            "Analysis expected every planned run to have a results folder, "
            "but some were missing.\n\n"
            f"{preview}{extra}"
        )


def evaluate_planned_run(row: Dict[str, object]) -> Dict[str, object]:
    branch_results_dir = Path(str(row["branch_results_dir"]))
    if not branch_results_dir.exists():
        raise FileNotFoundError(
            f"Missing results directory for planned run: {branch_results_dir}"
        )

    baseline_metrics_path = Path(str(row["baseline_metrics_path"]))
    post_metrics_path = Path(str(row["post_metrics_path"]))
    openhands_status_path = Path(str(row["openhands_status_path"]))
    explain_prompt_path = Path(str(row["explain_prompt_path"]))
    diff_patch_path = Path(str(row["diff_patch_path"]))
    baseline_cycle_catalog_path = Path(str(row["baseline_cycle_catalog_path"]))

    openhands_outcome = _read_openhands_outcome(openhands_status_path)
    no_change = _is_no_change_run(openhands_outcome)

    behavior_preserved = behavior_preserved_from_metrics(
        baseline_metrics_path=baseline_metrics_path,
        post_metrics_path=post_metrics_path,
    )

    structural = compute_structural_metrics(
        baseline_graph_path=Path(str(row["baseline_graph_path"])),
        baseline_scc_report_path=Path(str(row["baseline_scc_report_path"])),
        baseline_cycle_catalog_path=baseline_cycle_catalog_path,
        post_scc_report_path=Path(str(row["post_scc_report_path"])),
        post_graph_path=Path(str(row["post_graph_path"])),
        cycle_id=str(row["cycle_id"]),
        no_change=no_change,
    )

    structurally_evaluable = bool(structural["structurally_evaluable"])

    cycle_eliminated_raw = bool(structural["cycle_eliminated_raw"])
    structural_improvement_raw = bool(structural["structural_improvement_raw"])
    weakening_improvement_raw = bool(structural["weakening_improvement_raw"])
    global_structural_regression_raw = bool(structural["global_structural_regression_raw"])

    local_improvement_raw = structural_improvement_raw or weakening_improvement_raw

    cycle_broken = behavior_preserved and cycle_eliminated_raw
    local_improvement = (
        behavior_preserved
        and structurally_evaluable
        and local_improvement_raw
    )
    success = (
        cycle_broken
        and local_improvement
        and not global_structural_regression_raw
    )

    other_incomplete = not structurally_evaluable

    explanation_chars = compute_explanation_length(explain_prompt_path)
    files_modified, chars_changed = compute_diff_metrics(diff_patch_path)
    cycle_size = _read_cycle_size_from_catalog(
        baseline_cycle_catalog_path,
        str(row["cycle_id"]),
    )

    return {
        **row,
        "openhands_outcome": openhands_outcome,
        "no_change": int(no_change),
        "other_incomplete": int(other_incomplete),
        "structurally_evaluable": int(structurally_evaluable),
        "behavior_preserved": int(behavior_preserved),
        "cycle_broken": int(cycle_broken),
        "local_improvement": int(local_improvement),
        "success": int(success),
        "cycle_size": cycle_size,
        "cycle_eliminated_raw": int(cycle_eliminated_raw),
        "structural_improvement_raw": int(structural_improvement_raw),
        "weakening_improvement_raw": int(weakening_improvement_raw),
        "global_structural_regression_raw": int(global_structural_regression_raw),
        "global_regression_outside_target_raw": int(
            structural["global_regression_outside_target_raw"]
        ),
        "baseline_global_redundancy": int(structural["baseline_global_redundancy"]),
        "post_global_redundancy": int(structural["post_global_redundancy"]),
        "explanation_chars": explanation_chars,
        "files_modified": files_modified,
        "chars_changed": chars_changed,
    }


def build_all_runs_dataframe(
    config_path: Path,
    analysis_plan_path: Path,
) -> pd.DataFrame:
    planned_rows = iter_planned_runs(
        config_path=config_path,
        analysis_plan_path=analysis_plan_path,
    )

    validate_all_planned_runs_exist(planned_rows)

    df = pd.DataFrame(evaluate_planned_run(row) for row in planned_rows)
    if df.empty:
        return df

    plan = load_analysis_plan(analysis_plan_path)
    mode_order = {mode_id: i for i, mode_id in enumerate(plan.modes.keys())}

    df["_mode_order"] = df["mode_id"].map(mode_order).fillna(999).astype(int)
    df = (
        df.sort_values(
            by=["_mode_order", "repo", "cycle_id", "experiment_id"],
            kind="stable",
        )
        .drop(columns=["_mode_order"])
        .reset_index(drop=True)
    )

    return df


def write_all_runs_csv(
    config_path: Path,
    analysis_plan_path: Path,
    outdir: Path,
    filename: str = "all_runs.csv",
) -> Path:
    df = build_all_runs_dataframe(
        config_path=config_path,
        analysis_plan_path=analysis_plan_path,
    )

    out_path = outdir / "derived" / filename
    write_dataframe_csv(out_path, df)
    return out_path