#!/usr/bin/env python3
"""
RQ1 (iterationless): WITH vs WITHOUT explanations.

Outputs:
  - rq1_per_project.csv        # per repo *variant* aggregated rows
  - rq1_with_vs_without.csv    # two pooled rows (with vs without)
  - rq1_per_cycle.csv          # NEW: one row per (repo, cycle_id, condition) with cycle_size
"""

from __future__ import annotations
import argparse, csv, sys
from pathlib import Path
from typing import Dict, Any, List, Optional

from rq_utils import (
    read_repos_file,
    get_tests_pass_percent, get_scc_metrics,
    parse_cycles, branch_for, load_json_any, mean_or_none, safe_sub,
    cycle_size_from_baseline,
)

# Relative file locations inside a branch directory
ATD_METRICS = ["ATD_identification/ATD_metrics.json", "ATD_metrics.json"]
QUALITY_METRICS = ["code_quality_checks/metrics.json", "metrics.json"]

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

    WITH_ID  = args.exp_with
    WO_ID    = args.exp_without

    # every cycle row we collect (now includes unpaired)
    per_cycle_rows: List[Dict[str, Any]] = []
    # for project-level aggregation
    per_project_rows: List[Dict[str, Any]] = []

    for repo, baseline_branch, _src_rel in repos:
        repo_dir = results_root / repo
        baseline_dir = repo_dir / baseline_branch

        base_atd   = load_json_any(baseline_dir, ATD_METRICS)
        base_qual  = load_json_any(baseline_dir, QUALITY_METRICS)
        if base_atd is None or base_qual is None:
            print(f"[WARN] Missing baseline ATD or quality metrics for {repo}@{baseline_branch}", file=sys.stderr)
            continue

        pre = get_scc_metrics(base_atd)
        pre_edges = pre.get("total_edges_in_cyclic_sccs")
        pre_count = pre.get("scc_count")
        pre_nodes = pre.get("total_nodes_in_cyclic_sccs")
        pre_loc   = pre.get("total_loc_in_cyclic_sccs")
        base_tests = get_tests_pass_percent(base_qual)

        cids = cycles_map.get((repo, baseline_branch), [])[:]
        if not cids:
            continue

        def collect_one(dirpath: Path, cid: str, variant_label: str, condition_out: str) -> Optional[Dict[str, Any]]:
            atd = load_json_any(dirpath, ATD_METRICS)
            qual = load_json_any(dirpath, QUALITY_METRICS)
            if atd is None:
                return None
            post = get_scc_metrics(atd)
            post_edges = post.get("total_edges_in_cyclic_sccs")
            post_count = post.get("scc_count")
            post_nodes = post.get("total_nodes_in_cyclic_sccs")
            post_loc   = post.get("total_loc_in_cyclic_sccs")
            tests_pass = get_tests_pass_percent(qual) if qual is not None else None

            d_edges = safe_sub(post_edges, pre_edges)
            d_count = safe_sub(post_count, pre_count)
            d_nodes = safe_sub(post_nodes, pre_nodes)
            d_loc   = safe_sub(post_loc,   pre_loc)
            d_tests = safe_sub(tests_pass, base_tests)

            succ: Optional[bool] = None
            if (pre_edges is not None) and (post_edges is not None):
                tests_ok = (base_tests is None) or (tests_pass is None) or (tests_pass >= base_tests)
                succ = (post_edges < pre_edges) and tests_ok

            size = cycle_size_from_baseline(baseline_dir, cid)

            return {
                "repo": repo,
                "cycle_id": cid,
                "cycle_size": size,
                "variant_label": variant_label,   # e.g., expA / expA_without_explanation
                "condition": condition_out,       # "with" / "without" (nice for reading)
                "succ": succ,

                "pre_edges": pre_edges, "post_edges": post_edges, "delta_edges": d_edges,
                "pre_scc_count": pre_count, "post_scc_count": post_count, "delta_scc_count": d_count,
                "pre_nodes": pre_nodes, "post_nodes": post_nodes, "delta_nodes": d_nodes,
                "pre_loc": pre_loc, "post_loc": post_loc, "delta_loc": d_loc,

                "tests_pass_pct": tests_pass, "delta_tests_vs_base": d_tests,
            }

        for cid in cids:
            with_dir = repo_dir / branch_for(WITH_ID, cid)
            wo_dir   = repo_dir / branch_for(WO_ID,   cid)

            row_with = collect_one(with_dir, cid, WITH_ID, "with")
            row_wo   = collect_one(wo_dir,   cid, WO_ID,   "without")

            if row_with: per_cycle_rows.append(row_with)
            if row_wo:   per_cycle_rows.append(row_wo)

        # Project aggregation over all rows we gathered for this repo
        rows_repo = [r for r in per_cycle_rows if r["repo"] == repo]
        with_rows = [r for r in rows_repo if r["condition"] == "with"]
        wo_rows   = [r for r in rows_repo if r["condition"] == "without"]

        def agg_project(rows: List[Dict[str, Any]], label_out: str) -> Optional[Dict[str, Any]]:
            if not rows:
                return None
            def pull(k): return [r.get(k) for r in rows]
            succs = [r.get("succ") for r in rows]
            succ_vals = [s for s in succs if isinstance(s, bool)]
            succ_pct = (100.0 * sum(1 for s in succ_vals if s) / len(succ_vals)) if succ_vals else None

            return {
                "repo": repo,
                "variant": label_out,  # "with" / "without"
                "Success%": round(succ_pct, 2) if succ_pct is not None else None,
                "ΔEdges": mean_or_none(pull("delta_edges")),
                "ΔSCCcount": mean_or_none(pull("delta_scc_count")),
                "ΔNodes": mean_or_none(pull("delta_nodes")),
                "ΔLOC": mean_or_none(pull("delta_loc")),
                "ΔTests_vs_base": mean_or_none(pull("delta_tests_vs_base")),
            }

        row_with_p = agg_project(with_rows, "with")
        row_wo_p   = agg_project(wo_rows,   "without")
        if row_with_p: per_project_rows.append(row_with_p)
        if row_wo_p:   per_project_rows.append(row_wo_p)

    # ---------- Write per-project ----------
    proj_path = outdir / "rq1_per_project.csv"
    if per_project_rows:
        with proj_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(per_project_rows[0].keys()))
            w.writeheader()
            for r in per_project_rows:
                w.writerow(r)
        print(f"Wrote: {proj_path}")
    else:
        print("[WARN] No per-project rows produced", file=sys.stderr)

    # ---------- WITH vs WITHOUT pooled (across all per-cycle rows) ----------
    pool = {"with": [], "without": []}
    for r in per_cycle_rows:
        pool[r["condition"]].append(r)

    def rate_bool(xs: List[Optional[bool]]) -> Optional[float]:
        vals = [x for x in xs if isinstance(x, bool)]
        if not vals: return None
        return 100.0 * sum(1 for v in vals if v) / len(vals)

    def newcycle_rate(pre_counts: List[Optional[float]], post_counts: List[Optional[float]]) -> Optional[float]:
        flags: List[Optional[bool]] = []
        for a, b in zip(pre_counts, post_counts):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                flags.append(bool(b > a))
            else:
                flags.append(None)
        vals = [x for x in flags if isinstance(x, bool)]
        if not vals: return None
        return 100.0 * sum(1 for x in vals if x) / len(vals)

    rows_with_without: List[Dict[str, Any]] = []
    for label_out in ("with", "without"):
        rows = pool[label_out]
        if not rows:
            continue
        def pull(k): return [r.get(k) for r in rows]
        succ_pct = rate_bool(pull("succ"))
        tests_pct = mean_or_none(pull("tests_pass_pct"))
        newcyc = newcycle_rate(pull("pre_scc_count"), pull("post_scc_count"))
        rows_with_without.append({
            "Condition": label_out,
            "Success%": round(succ_pct, 2) if succ_pct is not None else None,
            "Tests%": round(tests_pct, 2) if tests_pct is not None else None,
            "NewCycle%": round(newcyc, 2) if newcyc is not None else None,
            "ΔEdges": mean_or_none(pull("delta_edges")),
            "ΔSCCcount": mean_or_none(pull("delta_scc_count")),
            "ΔNodes": mean_or_none(pull("delta_nodes")),
            "ΔLOC": mean_or_none(pull("delta_loc")),
        })

    wv_path = outdir / "rq1_with_vs_without.csv"
    if rows_with_without:
        with wv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows_with_without[0].keys()))
            w.writeheader()
            for r in rows_with_without:
                w.writerow(r)
        print(f"Wrote: {wv_path}")
    else:
        print("[WARN] No paired data to write to rq1_with_vs_without.csv", file=sys.stderr)

    # ---------- NEW: per-cycle table ----------
    if per_cycle_rows:
        # Choose readable column order
        fields = [
            "repo", "cycle_id", "cycle_size", "condition", "succ",
            "pre_edges","post_edges","delta_edges",
            "pre_scc_count","post_scc_count","delta_scc_count",
            "pre_nodes","post_nodes","delta_nodes",
            "pre_loc","post_loc","delta_loc",
            "tests_pass_pct","delta_tests_vs_base",
            "variant_label",  # keep the original label too (exp names)
        ]
        pc_path = outdir / "rq1_per_cycle.csv"
        with pc_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in per_cycle_rows:
                w.writerow({k: r.get(k) for k in fields})
        print(f"Wrote: {pc_path}")
    else:
        print("[WARN] No per-cycle rows produced", file=sys.stderr)

if __name__ == "__main__":
    main()
