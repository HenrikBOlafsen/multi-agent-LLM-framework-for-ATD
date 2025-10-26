#!/usr/bin/env python3
"""
RQ3 (iterationless): Aggregate outcomes by CYCLE SIZE. Multi-root aware.

Marker support:
- If a branch dir contains `.copied_metrics_marker`, we treat it as "no changes":
  post metrics = baseline metrics, tests = baseline tests (so deltas are 0, not a success).

- One CSV only: rq3_by_cycle_size.csv
- Two rows per size: Condition ∈ {"with","without"}
- Adds std dev columns and McNemar p-value per size (computed on success pairs).
"""
from __future__ import annotations
import argparse, csv, math, sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from rq_utils import (
    read_json, read_repos_file, get_tests_pass_percent, get_scc_metrics,
    ATD_METRICS, CQ_METRICS, parse_cycles, branch_for, cycle_size_from_baseline,
    safe_sub, mean_or_none, std_or_none, mcnemar_p, map_roots_exps
)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-roots", nargs="+", required=True)
    ap.add_argument("--exp-ids", nargs="+", required=True)
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--cycles-file", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    cfgs = map_roots_exps(args.results_roots, args.exp_ids)

    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    repos = read_repos_file(Path(args.repos_file))
    cycles_map = parse_cycles(Path(args.cycles_file))

    baseline_by_repo: Dict[str, str] = {repo: base for (repo, base, _src) in repos}

    per_cycle_rows: List[Dict[str, Any]] = []

    for results_root, WITH_ID, WO_ID in cfgs:
        results_root = Path(results_root)
        for (repo, base_branch), cycle_ids in cycles_map.items():
            if repo not in baseline_by_repo or baseline_by_repo[repo] != base_branch:
                continue

            repo_dir = results_root / repo
            base_dir = repo_dir / base_branch

            base_atd = read_json(base_dir / ATD_METRICS)
            base_qual = read_json(base_dir / CQ_METRICS)
            if base_atd is None or base_qual is None:
                print(f"[WARN] Missing baseline ATD or quality metrics for {repo}@{base_branch} under {results_root}", file=sys.stderr)
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

                    copied_marker = (new_dir / ".copied_metrics_marker").exists()
                    if copied_marker:
                        post_edges = pre_edges
                        post_count = pre_count
                        post_nodes = pre_nodes
                        post_loc   = pre_loc
                        tests_pass = base_tests
                    else:
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
                        "repo": repo,
                        "cycle_id": cid,
                        "exp_label": exp_label,
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
    from collections import defaultdict
    groups: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in per_cycle_rows:
        groups[(int(r["cycle_size"]), r["condition"])].append(r)

    def success_rate(rows: List[Dict[str, Any]]) -> Optional[float]:
        vals = [r["succ"] for r in rows if isinstance(r.get("succ"), bool)]
        if not vals: return None
        return 100.0 * sum(1 for v in vals if v) / len(vals)

    def mean_of(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
        xs = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
        return (sum(xs) / len(xs)) if xs else None

    def std_of(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
        xs = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
        if len(xs) < 2: return None
        m = sum(xs)/len(xs)
        return (sum((x-m)**2 for x in xs)/(len(xs)-1))**0.5

    # McNemar per size (paired in the same size bin)
    def mcnemar_by_size(size: int) -> Optional[float]:
        # pair by (repo, cycle_id, exp_label) within the given size
        with_map = {}; wo_map = {}
        for r in per_cycle_rows:
            if int(r["cycle_size"]) != int(size): continue
            k = (r["repo"], r["cycle_id"], r["exp_label"])
            if r["condition"] == "with": with_map[k] = r
            else: wo_map[k] = r
        b = c = 0
        for k in set(with_map.keys()).intersection(wo_map.keys()):
            w = with_map[k].get("succ"); o = wo_map[k].get("succ")
            if isinstance(w, bool) and isinstance(o, bool):
                if w and not o: b += 1
                elif o and not w: c += 1
        if b+c == 0: return None
        return mcnemar_p(b, c)

    out_rows: List[Dict[str, Any]] = []
    for (size, cond) in sorted(groups.keys(), key=lambda t: (t[0], t[1] != "with")):
        rows = groups[(size, cond)]
        out_rows.append({
            "CycleSize": size,
            "Condition": cond,
            "Success%": round(success_rate(rows), 2) if success_rate(rows) is not None else None,
            "ΔEdges_mean": mean_of(rows, "delta_edges"),
            "ΔEdges_std":  std_of(rows, "delta_edges"),
            "ΔSCCcount_mean": mean_of(rows, "delta_scc_count"),
            "ΔSCCcount_std":  std_of(rows, "delta_scc_count"),
            "ΔNodes_mean": mean_of(rows, "delta_nodes"),
            "ΔNodes_std":  std_of(rows, "delta_nodes"),
            "ΔLOC_mean": mean_of(rows, "delta_loc"),
            "ΔLOC_std":  std_of(rows, "delta_loc"),
            "Tests%_mean": mean_of(rows, "tests_pass_pct"),
            "ΔTests_vs_base_mean": mean_of(rows, "delta_tests_vs_base"),
            "n": len(rows),
            "Success_p_McNemar": mcnemar_by_size(size) if cond == "with" else None,  # one p per size
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
