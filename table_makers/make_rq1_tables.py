#!/usr/bin/env python3
"""
RQ1 (iterationless): WITH vs WITHOUT explanations.

Outputs:
  - rq1_per_project.csv        # per repo × condition, success-only deltas + rates (no NewCycle%)
  - rq1_with_vs_without.csv    # pooled (with vs without), success-only deltas + rates (no NewCycle%)
  - rq1_per_cycle.csv          # raw rows per (repo, cycle_id, condition) incl. cycle_size
"""

from __future__ import annotations
import argparse, csv, statistics, sys
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

# ------------- helpers -------------
def median_or_none(vals: List[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in vals if isinstance(v, (int, float))]
    if not xs:
        return None
    try:
        return float(statistics.median(xs))
    except Exception:
        return None

def rate_bool(xs: List[Optional[bool]]) -> Optional[float]:
    vals = [x for x in xs if isinstance(x, bool)]
    if not vals:
        return None
    return 100.0 * sum(1 for v in vals if v) / len(vals)

def pct(a: Optional[int], b: Optional[int]) -> Optional[float]:
    if not isinstance(a, int) or not isinstance(b, int) or b == 0:
        return None
    return 100.0 * a / b

# ------------- main -------------
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

    # Raw per-cycle rows (detail table)
    per_cycle_rows: List[Dict[str, Any]] = []
    # Per-project aggregates (output ready)
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
            post_nodes = post.get("total_nodes_in_cyclic_sccs")
            post_loc   = post.get("total_loc_in_cyclic_sccs")
            tests_pass = get_tests_pass_percent(qual) if qual is not None else None

            d_edges = safe_sub(post_edges, pre_edges)
            d_nodes = safe_sub(post_nodes, pre_nodes)
            d_loc   = safe_sub(post_loc,   pre_loc)

            # Success: edges decreased AND tests ok (or unavailable / unchanged allowed per rule)
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
                "condition": condition_out,       # "with" / "without"
                "succ": succ,

                "pre_edges": pre_edges, "post_edges": post_edges, "delta_edges": d_edges,
                "pre_nodes": pre_nodes, "post_nodes": post_nodes, "delta_nodes": d_nodes,
                "pre_loc": pre_loc,     "post_loc": post_loc,     "delta_loc":   d_loc,

                "tests_pass_pct": tests_pass,
                "delta_tests_vs_base": safe_sub(tests_pass, base_tests),
            }

        # collect all rows (unpaired allowed)
        for cid in cids:
            with_dir = repo_dir / branch_for(WITH_ID, cid)
            wo_dir   = repo_dir / branch_for(WO_ID,   cid)

            row_with = collect_one(with_dir, cid, WITH_ID, "with")
            row_wo   = collect_one(wo_dir,   cid, WO_ID,   "without")

            if row_with: per_cycle_rows.append(row_with)
            if row_wo:   per_cycle_rows.append(row_wo)

        # per-project aggregation over this repo's rows
        rows_repo = [r for r in per_cycle_rows if r["repo"] == repo]

        def aggregate_rows(rows: List[Dict[str, Any]], condition_label: str) -> Optional[Dict[str, Any]]:
            rows_c = [r for r in rows if r["condition"] == condition_label]
            if not rows_c:
                return None

            n_total = len(rows_c)
            n_success = sum(1 for r in rows_c if isinstance(r.get("succ"), bool) and r["succ"] is True)
            succ_pct = pct(n_success, n_total)

            # success-only deltas
            succ_rows = [r for r in rows_c if r.get("succ") is True]
            de_succ = [r.get("delta_edges") for r in succ_rows]
            dn_succ = [r.get("delta_nodes") for r in succ_rows]
            dl_succ = [r.get("delta_loc")   for r in succ_rows]

            # zero-change rate (on valid edge pairs)
            valid_edge_pairs = [r for r in rows_c if isinstance(r.get("pre_edges"), (int, float)) and isinstance(r.get("post_edges"), (int, float))]
            zero_change = [ (r["post_edges"] == r["pre_edges"]) for r in valid_edge_pairs ]

            tests_vals = [r.get("tests_pass_pct") for r in rows_c if isinstance(r.get("tests_pass_pct"), (int, float))]

            return {
                "repo": repo,
                "Condition": condition_label,               # "with" / "without"
                "n_total": n_total,
                "n_success": n_success,
                "Success%": round(succ_pct, 2) if succ_pct is not None else None,

                "ΔEdges_success_mean": mean_or_none(de_succ),
                "ΔEdges_success_median": median_or_none(de_succ),
                "ΔNodes_success_mean": mean_or_none(dn_succ),
                "ΔLOC_success_mean": mean_or_none(dl_succ),

                "ZeroChange%": round(rate_bool(zero_change), 2) if rate_bool(zero_change) is not None else None,
                "Tests%":      round(mean_or_none(tests_vals), 2) if mean_or_none(tests_vals) is not None else None,
            }

        row_with_p = aggregate_rows(rows_repo, "with")
        row_wo_p   = aggregate_rows(rows_repo, "without")
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

    def aggregate_pool(rows: List[Dict[str, Any]], condition_label: str) -> Optional[Dict[str, Any]]:
        if not rows:
            return None
        n_total = len(rows)
        n_success = sum(1 for r in rows if isinstance(r.get("succ"), bool) and r["succ"] is True)
        succ_pct = pct(n_success, n_total)

        succ_rows = [r for r in rows if r.get("succ") is True]
        de_succ = [r.get("delta_edges") for r in succ_rows]
        dn_succ = [r.get("delta_nodes") for r in succ_rows]
        dl_succ = [r.get("delta_loc")   for r in succ_rows]

        valid_edge_pairs = [r for r in rows if isinstance(r.get("pre_edges"), (int, float)) and isinstance(r.get("post_edges"), (int, float))]
        zero_change = [ (r["post_edges"] == r["pre_edges"]) for r in valid_edge_pairs ]

        tests_vals = [r.get("tests_pass_pct") for r in rows if isinstance(r.get("tests_pass_pct"), (int, float))]

        return {
            "Condition": condition_label,
            "n_total": n_total,
            "n_success": n_success,
            "Success%": round(succ_pct, 2) if succ_pct is not None else None,

            "ΔEdges_success_mean": mean_or_none(de_succ),
            "ΔEdges_success_median": median_or_none(de_succ),
            "ΔNodes_success_mean": mean_or_none(dn_succ),
            "ΔLOC_success_mean": mean_or_none(dl_succ),

            "ZeroChange%": round(rate_bool(zero_change), 2) if rate_bool(zero_change) is not None else None,
            "Tests%":      round(mean_or_none(tests_vals), 2) if mean_or_none(tests_vals) is not None else None,
        }

    rows_with_without: List[Dict[str, Any]] = []
    for label_out in ("with", "without"):
        agg = aggregate_pool(pool[label_out], label_out)
        if agg:
            rows_with_without.append(agg)

    wv_path = outdir / "rq1_with_vs_without.csv"
    if rows_with_without:
        with wv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows_with_without[0].keys()))
            w.writeheader()
            for r in rows_with_without:
                w.writerow(r)
        print(f"Wrote: {wv_path}")
    else:
        print("[WARN] No data for rq1_with_vs_without.csv", file=sys.stderr)

    # ---------- per-cycle (raw) ----------
    if per_cycle_rows:
        fields = [
            "repo", "cycle_id", "cycle_size", "condition", "succ",
            "pre_edges","post_edges","delta_edges",
            "pre_nodes","post_nodes","delta_nodes",
            "pre_loc","post_loc","delta_loc",
            "tests_pass_pct","delta_tests_vs_base",
            "variant_label",
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
