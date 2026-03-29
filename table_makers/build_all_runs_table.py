#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence

import pandas as pd

from table_loading import build_effectiveness_row, load_baseline_bundle, load_run_bundle
from table_utils import (
    RepoSpec,
    classify_outcome,
    cycle_size_from_catalog,
    load_cycle_definition,
    mode_ids_from_config,
    read_cycles_file,
    read_pipeline_config,
    read_repos_file,
    resolve_config_relative_path,
)


def die(msg: str) -> None:
    raise SystemExit(msg)


def parse_mode_runs(items: Sequence[str]) -> Dict[str, List[str]]:
    """
    Parse repeated CLI args of the form:
      modeA:exp1,exp2,exp3
      modeB:exp4,exp5,exp6
    """
    out: Dict[str, List[str]] = {}
    for raw in items:
        if ":" not in raw:
            die(f"Bad --mode-runs value {raw!r}. Expected MODE:exp1,exp2,...")
        mode, rhs = raw.split(":", 1)
        mode = mode.strip()
        runs = [x.strip() for x in rhs.split(",") if x.strip()]
        if not mode:
            die(f"Bad --mode-runs value {raw!r}: empty mode")
        if not runs:
            die(f"Bad --mode-runs value {raw!r}: empty run list")
        if mode in out:
            die(f"Duplicate --mode-runs for mode {mode!r}")
        out[mode] = runs
    return out


def normalize_selected_modes(
    available_mode_ids: List[str],
    requested_modes: List[str] | None,
) -> List[str]:
    if requested_modes:
        modes = list(requested_modes)
    else:
        modes = list(available_mode_ids)

    if not modes:
        die("No modes selected.")

    missing = [m for m in modes if m not in available_mode_ids]
    if missing:
        die(f"Requested mode(s) not found in config.modes: {missing}. Available: {available_mode_ids}")

    if len(set(modes)) != len(modes):
        die(f"Duplicate mode IDs in selection: {modes}")

    return modes


def build_mode_to_experiment_ids(
    selected_modes: List[str],
    shared_experiment_ids: List[str] | None,
    mode_runs_items: List[str],
) -> Dict[str, List[str]]:
    explicit = parse_mode_runs(mode_runs_items) if mode_runs_items else {}

    if explicit and shared_experiment_ids:
        die("Use either shared --experiment-ids or repeated --mode-runs, not both.")

    if explicit:
        missing = [m for m in selected_modes if m not in explicit]
        extra = [m for m in explicit if m not in selected_modes]
        if missing:
            die(f"Missing --mode-runs entries for selected modes: {missing}")
        if extra:
            die(f"--mode-runs specified for unselected modes: {extra}")
        return explicit

    if not shared_experiment_ids:
        die("You must provide either --experiment-ids or repeated --mode-runs.")

    return {mode_id: list(shared_experiment_ids) for mode_id in selected_modes}


def serialize_jsonish(value) -> str:
    return json.dumps(value, sort_keys=True) if value is not None else ""


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build one long-format CSV with one row per included run across all selected modes."
    )
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--modes", nargs="*")
    ap.add_argument("--experiment-ids", nargs="*")
    ap.add_argument(
        "--mode-runs",
        action="append",
        default=[],
        help="Repeated. Format: MODE:exp1,exp2,exp3",
    )
    args = ap.parse_args()

    config = read_pipeline_config(Path(args.config).resolve())
    repos_file = resolve_config_relative_path(str(config["repos_file"]))
    cycles_file = resolve_config_relative_path(str(config["cycles_file"]))
    results_root = resolve_config_relative_path(str(config["results_root"]))
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    repos = read_repos_file(repos_file)
    cycles = read_cycles_file(cycles_file)
    repo_map: Dict[str, RepoSpec] = {r.repo: r for r in repos}

    available_mode_ids = mode_ids_from_config(config)
    selected_modes = normalize_selected_modes(available_mode_ids, args.modes,)

    mode_to_experiment_ids = build_mode_to_experiment_ids(
        selected_modes=selected_modes,
        shared_experiment_ids=args.experiment_ids,
        mode_runs_items=args.mode_runs,
    )

    print(f"[INFO] selected modes: {selected_modes}", file=sys.stderr)
    for mode_id in selected_modes:
        print(f"[INFO] mode {mode_id}: experiment_ids={mode_to_experiment_ids[mode_id]}", file=sys.stderr)

    for cyc in cycles:
        repo_spec = repo_map.get(cyc.repo)
        if repo_spec is None:
            die(f"cycles file references unknown repo '{cyc.repo}'")
        if repo_spec.base_branch != cyc.base_branch:
            die(
                f"Base branch mismatch for repo {cyc.repo}: repos file has {repo_spec.base_branch}, "
                f"cycles file has {cyc.base_branch}"
            )

    baseline_cache = {repo_spec.repo: load_baseline_bundle(results_root, repo_spec) for repo_spec in repos}
    for repo_spec in repos:
        if baseline_cache[repo_spec.repo] is None:
            print(
                f"[WARN] Missing baseline ATD report for {repo_spec.repo}@{repo_spec.base_branch} under {results_root}",
                file=sys.stderr,
            )

    expected = len(cycles) * sum(len(mode_to_experiment_ids[m]) for m in selected_modes)
    print(f"[INFO] expected repo-cycle-mode-run combinations: {expected}", file=sys.stderr)

    all_rows: List[dict] = []
    inclusion_counter: Counter = Counter()
    excluded_counter: Counter = Counter()
    run_kind_counter: Counter = Counter()
    outcome_class_counter: Counter = Counter()

    for cyc in cycles:
        repo_spec = repo_map[cyc.repo]
        baseline = baseline_cache.get(repo_spec.repo)

        if baseline is None:
            excluded_counter["excluded_missing_baseline"] += sum(len(mode_to_experiment_ids[m]) for m in selected_modes)
            continue

        cycle_size = cycle_size_from_catalog(baseline["base_dir"], cyc.cycle_id)
        cycle_def = load_cycle_definition(baseline["base_dir"], cyc.cycle_id)
        if cycle_def is None:
            print(
                f"[WARN] Missing cycle definition in baseline catalog for {repo_spec.repo} {cyc.cycle_id}",
                file=sys.stderr,
            )
            excluded_counter["excluded_missing_cycle_definition"] += sum(
                len(mode_to_experiment_ids[m]) for m in selected_modes
            )
            continue

        for mode_id in selected_modes:
            for experiment_id in mode_to_experiment_ids[mode_id]:
                run, reason, branch_dir = load_run_bundle(
                    results_root=results_root,
                    repo_spec=repo_spec,
                    experiment_id=experiment_id,
                    mode_id=mode_id,
                    cycle_id=cyc.cycle_id,
                    baseline=baseline,
                )

                if run is None:
                    excluded_counter[reason] += 1
                    print(
                        f"[WARN] Excluding run: repo={repo_spec.repo} cycle={cyc.cycle_id} "
                        f"mode={mode_id} experiment={experiment_id} reason={reason}",
                        file=sys.stderr,
                    )
                    continue

                inclusion_counter[reason] += 1
                run_kind_counter[str(run["run_kind"])] += 1

                row = build_effectiveness_row(
                    repo=repo_spec.repo,
                    experiment_id=experiment_id,
                    cycle_id=cyc.cycle_id,
                    cycle_size=cycle_size,
                    mode_id=mode_id,
                    baseline=baseline,
                    run=run,
                    cycle_def=cycle_def,
                    branch_dir=branch_dir,
                )

                row["base_branch"] = repo_spec.base_branch
                row["language"] = repo_spec.language
                row["entry"] = repo_spec.entry
                row["branch_dir"] = str(branch_dir)
                row["cycle_length"] = cycle_def.get("length")
                row["cycle_nodes"] = serialize_jsonish(cycle_def.get("nodes"))
                row["cycle_edges"] = serialize_jsonish(cycle_def.get("edges"))
                row["cycle_scc_id"] = cycle_def.get("scc_id")

                row["baseline_test_counts_json"] = serialize_jsonish(row.get("baseline_test_counts"))
                row["test_counts_json"] = serialize_jsonish(row.get("test_counts"))

                row["outcome_class"] = classify_outcome(row)
                outcome_class_counter[row["outcome_class"]] += 1

                all_rows.append(row)

    if not all_rows:
        die("No rows produced. Check config paths, mode selection, and experiment IDs.")

    print(f"[INFO] included rows={len(all_rows)} excluded rows={sum(excluded_counter.values())}", file=sys.stderr)

    print("[INFO] inclusion reasons:", file=sys.stderr)
    for k, v in sorted(inclusion_counter.items()):
        print(f"  {k}: {v}", file=sys.stderr)

    print("[INFO] excluded reasons:", file=sys.stderr)
    for k, v in sorted(excluded_counter.items()):
        print(f"  {k}: {v}", file=sys.stderr)

    print("[INFO] run kinds:", file=sys.stderr)
    for k, v in sorted(run_kind_counter.items()):
        print(f"  {k}: {v}", file=sys.stderr)

    print("[INFO] outcome classes:", file=sys.stderr)
    for k, v in sorted(outcome_class_counter.items()):
        print(f"  {k}: {v}", file=sys.stderr)

    df = pd.DataFrame(all_rows)
    sort_cols = [c for c in ["repo", "cycle_id", "mode", "experiment_id"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols).reset_index(drop=True)

    all_runs_path = outdir / "all_runs.csv"
    df.to_csv(all_runs_path, index=False)
    print(f"Wrote: {all_runs_path}", file=sys.stderr)

    accounting_rows = []
    for reason, count in sorted(inclusion_counter.items()):
        accounting_rows.append({"bucket": "included", "reason": reason, "count": count})
    for reason, count in sorted(excluded_counter.items()):
        accounting_rows.append({"bucket": "excluded", "reason": reason, "count": count})
    for reason, count in sorted(run_kind_counter.items()):
        accounting_rows.append({"bucket": "run_kind", "reason": reason, "count": count})
    for reason, count in sorted(outcome_class_counter.items()):
        accounting_rows.append({"bucket": "outcome_class", "reason": reason, "count": count})

    accounting_df = pd.DataFrame(accounting_rows)
    accounting_path = outdir / "run_accounting_summary.csv"
    accounting_df.to_csv(accounting_path, index=False)
    print(f"Wrote: {accounting_path}", file=sys.stderr)


if __name__ == "__main__":
    main()