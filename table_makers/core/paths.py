from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunArtifactPaths:
    branch_name: str
    branch_results_dir: Path
    baseline_results_dir: Path

    baseline_metrics_path: Path
    post_metrics_path: Path

    baseline_graph_path: Path
    post_graph_path: Path

    baseline_scc_report_path: Path
    post_scc_report_path: Path

    baseline_cycle_catalog_path: Path

    openhands_status_path: Path
    explain_prompt_path: Path
    diff_patch_path: Path


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


def metrics_json_path(results_dir: Path) -> Path:
    return results_dir / "code_quality_checks" / "metrics.json"


def dependency_graph_json_path(results_dir: Path) -> Path:
    return results_dir / "ATD_identification" / "dependency_graph.json"


def scc_report_json_path(results_dir: Path) -> Path:
    return results_dir / "ATD_identification" / "scc_report.json"


def cycle_catalog_json_path(results_dir: Path) -> Path:
    return results_dir / "ATD_identification" / "cycle_catalog.json"


def openhands_status_json_path(results_dir: Path) -> Path:
    return results_dir / "openhands" / "status.json"


def explain_prompt_txt_path(results_dir: Path) -> Path:
    return results_dir / "explain" / "prompt.txt"


def diff_patch_path(results_dir: Path) -> Path:
    return results_dir / "openhands" / "git_diff.patch"


def build_run_artifact_paths(
    *,
    results_root: Path,
    repo: str,
    base_branch: str,
    experiment_id: str,
    mode_id: str,
    cycle_id: str,
) -> RunArtifactPaths:
    branch_name = make_refactor_branch_name(experiment_id, mode_id, cycle_id)

    branch_results_dir = results_dir_for_branch(
        results_root=results_root,
        repo_name=repo,
        branch_name=branch_name,
    )
    baseline_results_dir = results_dir_for_branch(
        results_root=results_root,
        repo_name=repo,
        branch_name=base_branch,
    )

    return RunArtifactPaths(
        branch_name=branch_name,
        branch_results_dir=branch_results_dir,
        baseline_results_dir=baseline_results_dir,
        baseline_metrics_path=metrics_json_path(baseline_results_dir),
        post_metrics_path=metrics_json_path(branch_results_dir),
        baseline_graph_path=dependency_graph_json_path(baseline_results_dir),
        post_graph_path=dependency_graph_json_path(branch_results_dir),
        baseline_scc_report_path=scc_report_json_path(baseline_results_dir),
        post_scc_report_path=scc_report_json_path(branch_results_dir),
        baseline_cycle_catalog_path=cycle_catalog_json_path(baseline_results_dir),
        openhands_status_path=openhands_status_json_path(branch_results_dir),
        explain_prompt_path=explain_prompt_txt_path(branch_results_dir),
        diff_patch_path=diff_patch_path(branch_results_dir),
    )