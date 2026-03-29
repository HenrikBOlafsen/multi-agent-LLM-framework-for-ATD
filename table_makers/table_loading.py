#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from table_utils import (
    branch_for_run,
    cycle_still_present_in_scc_report,
    get_explain_total_tokens,
    get_openhands_total_tokens,
    get_scc_metrics,
    get_test_counts,
    read_json,
    results_dir_for_branch,
    safe_sub,
    strict_test_counts_ok,
)

ATD_REPORT_REL = Path("ATD_identification") / "scc_report.json"
QUALITY_REL = Path("code_quality_checks") / "metrics.json"
STATUS_OPENHANDS_REL = Path("status_openhands.json")
STATUS_METRICS_REL = Path("status_metrics.json")
EXPLAIN_USAGE_REL = Path("explain") / "llm_usage.json"
OPENHANDS_TRAJECTORY_REL = Path("openhands") / "trajectory.json"


def load_baseline_bundle(results_root: Path, repo_spec: Any) -> Optional[Dict[str, Any]]:
    base_dir = results_dir_for_branch(results_root, repo_spec.repo, repo_spec.base_branch)
    scc_report = read_json(base_dir / ATD_REPORT_REL)
    metrics = read_json(base_dir / QUALITY_REL)
    if scc_report is None:
        return None

    scc = get_scc_metrics(scc_report)
    return {
        "base_dir": base_dir,
        "pre_edges": scc["total_edges_in_cyclic_sccs"],
        "pre_nodes": scc["total_nodes_in_cyclic_sccs"],
        "pre_loc": scc["total_loc_in_cyclic_sccs"],
        "baseline_test_counts": get_test_counts(metrics, repo_spec.language),
    }


def _openhands_status_fields(status_openhands: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not status_openhands:
        return {
            "phase_outcome": "",
            "phase_reason": "",
            "openhands_outcome": "",
            "openhands_reason": "",
        }

    artifacts = status_openhands.get("artifacts") or {}
    return {
        "phase_outcome": str(status_openhands.get("outcome", "")).strip(),
        "phase_reason": str(status_openhands.get("reason", "")).strip(),
        "openhands_outcome": str(artifacts.get("openhands_outcome", "")).strip(),
        "openhands_reason": str(artifacts.get("openhands_reason", "")).strip(),
    }


def _metrics_status_fields(status_metrics: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not status_metrics:
        return {"metrics_phase_outcome": "", "metrics_phase_reason": ""}
    return {
        "metrics_phase_outcome": str(status_metrics.get("outcome", "")).strip(),
        "metrics_phase_reason": str(status_metrics.get("reason", "")).strip(),
    }


def _status_payload(
    oh: Dict[str, str],
    mt: Dict[str, str],
    *,
    post_scc_report: Optional[Dict[str, Any]],
    post_edges: Optional[float],
    post_nodes: Optional[float],
    post_loc: Optional[float],
    test_counts: Optional[Dict[str, int]],
    run_kind: str,
    evaluable_structure: bool,
    evaluable_tests: bool,
) -> Dict[str, Any]:
    return {
        "post_scc_report": post_scc_report,
        "post_edges": post_edges,
        "post_nodes": post_nodes,
        "post_loc": post_loc,
        "test_counts": test_counts,
        "run_kind": run_kind,
        "include_in_effectiveness": True,
        "evaluable_structure": evaluable_structure,
        "evaluable_tests": evaluable_tests,
        "status_openhands_outcome": oh["phase_outcome"],
        "status_openhands_reason": oh["phase_reason"],
        "openhands_outcome": oh["openhands_outcome"],
        "openhands_reason": oh["openhands_reason"],
        "status_metrics_outcome": mt["metrics_phase_outcome"],
        "status_metrics_reason": mt["metrics_phase_reason"],
    }


def _missing_metrics_payload(
    baseline: Dict[str, Any],
    oh: Dict[str, str],
    mt: Dict[str, str],
    *,
    run_kind: str,
    use_baseline_post: bool = False,
) -> Dict[str, Any]:
    if use_baseline_post:
        return _status_payload(
            oh,
            mt,
            post_scc_report=None,
            post_edges=baseline["pre_edges"],
            post_nodes=baseline["pre_nodes"],
            post_loc=baseline["pre_loc"],
            test_counts=baseline["baseline_test_counts"],
            run_kind=run_kind,
            evaluable_structure=True,
            evaluable_tests=True,
        )

    return _status_payload(
        oh,
        mt,
        post_scc_report=None,
        post_edges=None,
        post_nodes=None,
        post_loc=None,
        test_counts=None,
        run_kind=run_kind,
        evaluable_structure=False,
        evaluable_tests=False,
    )


def load_run_bundle(
    *,
    results_root: Path,
    repo_spec: Any,
    experiment_id: str,
    mode_id: str,
    cycle_id: str,
    baseline: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str, Path]:
    branch_name = branch_for_run(experiment_id, mode_id, cycle_id)
    branch_dir = results_dir_for_branch(results_root, repo_spec.repo, branch_name)

    scc_report = read_json(branch_dir / ATD_REPORT_REL)
    metrics = read_json(branch_dir / QUALITY_REL)
    status_openhands = read_json(branch_dir / STATUS_OPENHANDS_REL)
    status_metrics = read_json(branch_dir / STATUS_METRICS_REL)

    oh = _openhands_status_fields(status_openhands)
    mt = _metrics_status_fields(status_metrics)

    if scc_report is not None:
        scc = get_scc_metrics(scc_report)
        run_kind = "metrics"
        if mt["metrics_phase_outcome"] and mt["metrics_phase_outcome"] != "ok":
            run_kind = f"metrics_artifacts_present_but_status_{mt['metrics_phase_outcome']}"
        return (
            _status_payload(
                oh,
                mt,
                post_scc_report=scc_report,
                post_edges=scc["total_edges_in_cyclic_sccs"],
                post_nodes=scc["total_nodes_in_cyclic_sccs"],
                post_loc=scc["total_loc_in_cyclic_sccs"],
                test_counts=get_test_counts(metrics, repo_spec.language),
                run_kind=run_kind,
                evaluable_structure=True,
                evaluable_tests=True,
            ),
            "included_metrics",
            branch_dir,
        )

    if not status_openhands:
        return (None, "excluded_missing_openhands_status", branch_dir)

    phase_outcome = oh["phase_outcome"]
    openhands_outcome = oh["openhands_outcome"]

    if openhands_outcome == "no_changes":
        return (
            _missing_metrics_payload(baseline, oh, mt, run_kind="no_changes", use_baseline_post=True),
            "included_no_changes",
            branch_dir,
        )

    if phase_outcome == "skipped":
        return (None, f"excluded_pre_openhands_{oh['phase_reason'] or 'skipped'}", branch_dir)

    if phase_outcome == "blocked" or openhands_outcome == "blocked":
        return (
            _missing_metrics_payload(baseline, oh, mt, run_kind="openhands_blocked"),
            "included_openhands_blocked",
            branch_dir,
        )

    if phase_outcome == "failed" or openhands_outcome in {"failed", "llm_error", "config_error"}:
        return (
            _missing_metrics_payload(baseline, oh, mt, run_kind="openhands_failed"),
            "included_openhands_failed",
            branch_dir,
        )

    if openhands_outcome == "committed":
        mapping = {
            "blocked": ("metrics_blocked", "included_metrics_blocked"),
            "failed": ("metrics_failed", "included_metrics_failed"),
            "skipped": ("metrics_skipped_after_commit", "included_metrics_skipped_after_commit"),
        }
        if mt["metrics_phase_outcome"] in mapping:
            run_kind, reason = mapping[mt["metrics_phase_outcome"]]
            return (_missing_metrics_payload(baseline, oh, mt, run_kind=run_kind), reason, branch_dir)

        return (
            _missing_metrics_payload(baseline, oh, mt, run_kind="metrics_missing_after_commit"),
            "included_metrics_missing_after_commit",
            branch_dir,
        )

    return (
        None,
        f"excluded_openhands_unclassified_phase={phase_outcome or '<empty>'}_oh={openhands_outcome or '<empty>'}",
        branch_dir,
    )


def build_effectiveness_row(
    *,
    repo: str,
    experiment_id: str,
    cycle_id: str,
    cycle_size: Optional[int],
    mode_id: str,
    baseline: Dict[str, Any],
    run: Dict[str, Any],
    cycle_def: Dict[str, Any],
    branch_dir: Path,
) -> Dict[str, Any]:
    pre_edges = baseline["pre_edges"]
    pre_nodes = baseline["pre_nodes"]
    pre_loc = baseline["pre_loc"]
    base_test_counts = baseline["baseline_test_counts"]

    post_edges = run["post_edges"]
    post_nodes = run["post_nodes"]
    post_loc = run["post_loc"]
    post_test_counts = run["test_counts"]

    global_edges_decreased = None
    if isinstance(pre_edges, (int, float)) and isinstance(post_edges, (int, float)):
        global_edges_decreased = post_edges < pre_edges

    if run["run_kind"] == "no_changes":
        cycle_still_present = True
    elif run["evaluable_structure"]:
        cycle_still_present = cycle_still_present_in_scc_report(cycle_def, run["post_scc_report"])
    else:
        cycle_still_present = None

    target_cycle_removed = None if cycle_still_present is None else (not cycle_still_present)

    tests_ok = strict_test_counts_ok(base_test_counts, post_test_counts)
    if run["evaluable_structure"]:
        succ = (
            bool(global_edges_decreased and target_cycle_removed and tests_ok)
            if global_edges_decreased is not None and target_cycle_removed is not None
            else False
        )
    else:
        succ = False

    explain_total_tokens = get_explain_total_tokens(branch_dir / EXPLAIN_USAGE_REL)
    openhands_total_tokens = get_openhands_total_tokens(branch_dir / OPENHANDS_TRAJECTORY_REL)
    total_llm_tokens = None
    if explain_total_tokens is not None and openhands_total_tokens is not None:
        total_llm_tokens = int(explain_total_tokens) + int(openhands_total_tokens)

    return {
        "repo": repo,
        "experiment_id": experiment_id,
        "cycle_id": cycle_id,
        "cycle_size": cycle_size,
        "mode": mode_id,
        "run_kind": run["run_kind"],
        "include_in_effectiveness": run["include_in_effectiveness"],
        "evaluable_structure": run["evaluable_structure"],
        "evaluable_tests": run["evaluable_tests"],
        "status_openhands_outcome": run["status_openhands_outcome"],
        "status_openhands_reason": run["status_openhands_reason"],
        "openhands_outcome": run["openhands_outcome"],
        "openhands_reason": run["openhands_reason"],
        "status_metrics_outcome": run["status_metrics_outcome"],
        "status_metrics_reason": run["status_metrics_reason"],
        "global_edges_decreased": global_edges_decreased,
        "target_cycle_removed": target_cycle_removed,
        "succ": succ,
        "pre_edges": pre_edges,
        "post_edges": post_edges,
        "delta_edges": safe_sub(post_edges, pre_edges),
        "pre_nodes": pre_nodes,
        "post_nodes": post_nodes,
        "delta_nodes": safe_sub(post_nodes, pre_nodes),
        "pre_loc": pre_loc,
        "post_loc": post_loc,
        "delta_loc": safe_sub(post_loc, pre_loc),
        "baseline_test_counts": base_test_counts,
        "test_counts": post_test_counts,
        "explain_total_tokens": explain_total_tokens,
        "openhands_total_tokens": openhands_total_tokens,
        "total_llm_tokens": total_llm_tokens,
    }