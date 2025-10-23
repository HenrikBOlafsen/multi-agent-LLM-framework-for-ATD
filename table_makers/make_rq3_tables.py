#!/usr/bin/env python3
"""
RQ3 (iterationless): Aggregate outcomes by CYCLE SIZE.

- One CSV only: rq3_by_cycle_size.csv
- Two rows per size: Condition ∈ {"with","without"}
- Columns mirror RQ1 aggregate columns.
"""

from __future__ import annotations
import argparse, csv, math, sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from rq_utils import (
    read_json, read_repos_file,
    get_tests_pass_percent, get_scc_metrics,
    ATD_METRICS, CQ_METRICS,
    parse_cycles, branch_for, cycle_size_from_baseline, safe_sub,
)

def mean_or_none(vals: List[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in vals if isinstance(v, (int, float))]
    return (sum(xs) / len(xs)) if xs else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", required=True)
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--cycles-file", required=True)
    ap.add_argument("--exp-with", required=True)
    ap.add_argument("--exp-without", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    results_root = Path(args.results_root)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    repos = read_repos_file(Path(args.repos_file))
    cycles_map = parse_cycles(Path(args.cycles_file))

    baseline_by_repo: Dict[str, str] = {repo: base for (repo, base, _src) in repos}
    WITH_ID, WO_ID = args.exp_with, args.exp_without

    per_cycle_rows: List[Dict[str, Any]] = []

    for (repo, base_branch), cycle_ids in cycles_map.items():
        if repo not in baseline_by_repo or baseline_by_repo[repo] != base_branch:
            continue

        repo_dir = results_root / repo
        base_dir = repo_dir / base_branch

        base_atd = read_json(base_dir / ATD_METRICS)
        base_qual = read_json(base_dir / CQ_METRICS)
        if base_atd is None or base_qual is None:
            print(f"[WARN] Missing baseline ATD or quality metrics for {repo}@{base_branch}", file=sys.stderr)
            continue

        pre = get_scc_metrics(base_atd)
        pre_edges = pre.get("total_edges_in_cyclic_sccs")
        pre_count = pre.get("scc_count")
        pre_nodes = pre.get("total_nodes_in_cyclic_sccs")
        pre_loc   = pre.get("total_loc_in_cyclic_sccs")
        base_tests = get_tests_pass_percent(base_qual)

        for cid in cycle_ids:
            size = cycle_size_from_baseline(base_dir, cid)
            if size is None:
                print(f"[INFO] Skip {repo}@{base_branch} cycle {cid}: size not found", file=sys.stderr)
                continue

            for variant_label in ("with", "without"):
                exp_label = WITH_ID if variant_label == "with" else WO_ID
                new_dir = repo_dir / branch_for(exp_label, cid)

                post_qual = read_json(new_dir / CQ_METRICS)
                post_atd  = read_json(new_dir / ATD_METRICS)
                if post_atd is None:
                    continue

                post = get_scc_metrics(post_atd)
                post_edges = post.get("total_edges_in_cyclic_sccs")
                post_count = post.get("scc_count")
                post_nodes = post.get("total_nodes_in_cyclic_sccs")
                post_loc   = post.get("total_loc_in_cyclic_sccs")
                tests_pass = get_tests_pass_percent(post_qual) if post_qual is not None else None

                d_edges = safe_sub(post_edges, pre_edges)
                d_count = safe_sub(post_count, pre_count)
                d_nodes = safe_sub(post_nodes, pre_nodes)
                d_loc   = safe_sub(post_loc,   pre_loc)
                d_tests = safe_sub(tests_pass, base_tests)

                succ: Optional[bool] = None
                if (pre_edges is not None) and (post_edges is not None):
                    tests_ok = (base_tests is None) or (tests_pass is None) or (tests_pass >= base_tests)
                    succ = (post_edges < pre_edges) and tests_ok

                per_cycle_rows.append({
                    "cycle_size": int(size),
                    "condition": variant_label,
                    "succ": succ,
                    "delta_edges": d_edges,
                    "delta_scc_count": d_count,
                    "delta_nodes": d_nodes,
                    "delta_loc": d_loc,
                    "tests_pass_pct": tests_pass,
                    "delta_tests_vs_base": d_tests,
                })

    # Aggregate by (cycle_size, condition)
    groups: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for r in per_cycle_rows:
        groups.setdefault((int(r["cycle_size"]), r["condition"]), []).append(r)

    def success_rate(rows: List[Dict[str, Any]]) -> Optional[float]:
        vals = [r["succ"] for r in rows if isinstance(r.get("succ"), bool)]
        if not vals: return None
        return 100.0 * sum(1 for v in vals if v) / len(vals)

    def mean_of(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
        xs = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
        return (sum(xs) / len(xs)) if xs else None

    out_rows: List[Dict[str, Any]] = []
    for (size, cond) in sorted(groups.keys(), key=lambda t: (t[0], t[1] != "with")):
        rows = groups[(size, cond)]
        out_rows.append({
            "CycleSize": size,
            "Condition": cond,
            "Success%": round(success_rate(rows), 2) if success_rate(rows) is not None else None,
            "ΔEdges": mean_of(rows, "delta_edges"),
            "ΔSCCcount": mean_of(rows, "delta_scc_count"),
            "ΔNodes": mean_of(rows, "delta_nodes"),
            "ΔLOC": mean_of(rows, "delta_loc"),
            "Tests%": mean_of(rows, "tests_pass_pct"),
            "ΔTests_vs_base": mean_of(rows, "delta_tests_vs_base"),
            "n": len(rows),
        })

    out_path = outdir / "rq3_by_cycle_size.csv"
    if out_rows:
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            w.writeheader()
            for r in out_rows:
                w.writerow(r)
        print(f"Wrote: {out_path}")
    else:
        print("[WARN] No rows produced for rq3_by_cycle_size.csv", file=sys.stderr)

if __name__ == "__main__":
    main()
