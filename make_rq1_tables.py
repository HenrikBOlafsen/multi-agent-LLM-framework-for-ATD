#!/usr/bin/env python3
"""
RQ1: With vs. Without Explanations (paired) for autonomous refactoring.

Outputs:
  - rq1_per_target.csv      # per repo/iter/variant with deltas (no pressure columns)
  - rq1_per_project.csv     # per repo *variant* rows: repo (with), repo (without), using the latest iter
  - rq1_with_vs_without.csv # TWO ROWS: aggregated WITH vs WITHOUT over *paired* targets (no 'Mean' prefixes)

Success rule (aggregate-based, relaxed tests):
  Success iff:
    1) total_edges_in_cyclic_sccs decreased vs baseline (strictly less), AND
    2) tests rule:
       - if both baseline and run tests% exist -> run >= baseline
       - if either missing -> do NOT block success

Note: We no longer write rq1_overview.csv.
"""

from __future__ import annotations
import argparse, csv, math, sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# rq_utils helpers available in your project
from rq_utils import (
    read_json, read_repos_file, list_variant_iters,
    get_tests_pass_percent, get_scc_metrics,
)

# Relative file locations inside a branch directory
ATD_METRICS = ["ATD_identification/ATD_metrics.json", "ATD_metrics.json"]
QUALITY_METRICS = ["code_quality_checks/metrics.json", "metrics.json"]

def load_json_any(base: Path, candidates: List[str]) -> Optional[Dict[str, Any]]:
    for rel in candidates:
        p = base / rel
        if p.exists():
            return read_json(p)
    return None

def mean_or_none(vals: List[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in vals if isinstance(v, (int, float)) and not math.isnan(v)]
    return (sum(xs) / len(xs)) if xs else None

def safe_sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a) - float(b)

def pick_latest_iter_row(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the row with the highest 'iter' from rows (same repo+variant)."""
    if not rows:
        return None
    best = None
    best_it = -10**9
    for r in rows:
        it = r.get("iter")
        if isinstance(it, int) and it > best_it:
            best, best_it = r, it
    return best

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", required=True)
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--exp-with", required=True)
    ap.add_argument("--exp-without", required=True)
    ap.add_argument("--max-iters", type=int, default=1)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--rq2-aggregate", choices=["none", "final"], default="none")
    args = ap.parse_args()

    results_root = Path(args.results_root)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    # repos.txt -> [(repo, baseline_branch, src_rel)]
    repos = read_repos_file(Path(args.repos_file))
    WITH_ID  = args.exp_with
    WO_ID    = args.exp_without

    per_target_rows: List[Dict[str, Any]] = []
    per_project_rows: List[Dict[str, Any]] = []

    # ---------- Collect per-target rows ----------
    for repo, baseline_branch, _src_rel in repos:
        repo_dir = results_root / repo
        baseline_dir = repo_dir / baseline_branch

        base_atd   = load_json_any(baseline_dir, ATD_METRICS)
        base_qual  = load_json_any(baseline_dir, QUALITY_METRICS)

        if base_atd is None or base_qual is None:
            print(f"[WARN] Missing baseline ATD or quality metrics for {repo}", file=sys.stderr)
            continue

        pre = get_scc_metrics(base_atd)
        pre_edges = pre.get("total_edges_in_cyclic_sccs")
        pre_count = pre.get("scc_count")
        pre_nodes = pre.get("total_nodes_in_cyclic_sccs")
        pre_loc   = pre.get("total_loc_in_cyclic_sccs")
        base_tests = get_tests_pass_percent(base_qual)  # may be None

        # list_variant_iters(repo_dir, [expid], max_iters) -> {expid: [(iter, path), ...]}
        per_with = list_variant_iters(repo_dir, [WITH_ID], args.max_iters).get(WITH_ID, [])
        per_wo   = list_variant_iters(repo_dir, [WO_ID],   args.max_iters).get(WO_ID,   [])
        it_to_with = {it: path for it, path in per_with}
        it_to_wo   = {it: path for it, path in per_wo}

        # Collect per-target rows for both variants
        def collect_variant_rows(vlabel: str, vlist: List[Tuple[int, Path]]):
            for it, it_root in vlist:
                atd = load_json_any(it_root, ATD_METRICS)
                qual = load_json_any(it_root, QUALITY_METRICS)
                if atd is None:
                    continue
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

                # Success rule
                succ: Optional[bool] = None
                if (pre_edges is not None) and (post_edges is not None):
                    tests_ok = (base_tests is None) or (tests_pass is None) or (tests_pass >= base_tests)
                    succ = (post_edges < pre_edges) and tests_ok

                per_target_rows.append({
                    "repo": repo,
                    "variant": vlabel,
                    "iter": it,
                    "succ": succ,

                    "pre_edges": pre_edges,
                    "post_edges": post_edges,
                    "delta_edges": d_edges,

                    "pre_scc_count": pre_count,
                    "post_scc_count": post_count,
                    "delta_scc_count": d_count,

                    "pre_nodes": pre_nodes,
                    "post_nodes": post_nodes,
                    "delta_nodes": d_nodes,

                    "pre_loc": pre_loc,
                    "post_loc": post_loc,
                    "delta_loc": d_loc,

                    "tests_pass_pct": tests_pass,
                    "delta_tests_vs_base": d_tests,
                })

        collect_variant_rows(WITH_ID, per_with)
        collect_variant_rows(WO_ID,   per_wo)

        # ---------- Per-project rows (no averaging; pick latest iter per variant) ----------
        rows_repo = [r for r in per_target_rows if r["repo"] == repo]
        with_rows = [r for r in rows_repo if r["variant"] == WITH_ID]
        wo_rows   = [r for r in rows_repo if r["variant"] == WO_ID]

        latest_with    = pick_latest_iter_row(with_rows)
        latest_without = pick_latest_iter_row(wo_rows)

        def to_project_row(r: Optional[Dict[str, Any]], variant_label: str) -> Optional[Dict[str, Any]]:
            if r is None:
                return None
            s = r.get("succ")
            s_pct = (100.0 if s is True else (0.0 if s is False else None))
            return {
                "repo": r["repo"],
                "variant": variant_label,  # "with" / "without"
                "iter": r["iter"],
                "Success%": s_pct,
                "ΔEdges": r.get("delta_edges"),
                "ΔSCCcount": r.get("delta_scc_count"),
                "ΔNodes": r.get("delta_nodes"),
                "ΔLOC": r.get("delta_loc"),
                "ΔTests_vs_base": r.get("delta_tests_vs_base"),
            }

        row_with = to_project_row(latest_with, "with")
        row_without = to_project_row(latest_without, "without")

        # Order: repo (with), then repo (without)
        if row_with is not None:
            per_project_rows.append(row_with)
        if row_without is not None:
            per_project_rows.append(row_without)

    # ---------- Write per-target ----------
    tgt_path = outdir / "rq1_per_target.csv"
    if per_target_rows:
        with tgt_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(per_target_rows[0].keys()))
            w.writeheader()
            for r in per_target_rows:
                w.writerow(r)
        print(f"Wrote: {tgt_path}")
    else:
        print("[WARN] No per-target rows produced", file=sys.stderr)

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

    # ---------- Build WITH vs WITHOUT (two rows, pooled over paired targets) ----------
    # Index per-target rows for fast lookup
    idx = {(r["repo"], r["iter"], r["variant"]): r for r in per_target_rows}
    cond_vectors = {"with": {}, "without": {}}
    # pooled across repos/iters where BOTH exist
    for repo, _, _ in repos:
        with_iters  = {it for (it, _) in list_variant_iters(results_root / repo, [WITH_ID], args.max_iters).get(WITH_ID, [])}
        wo_iters    = {it for (it, _) in list_variant_iters(results_root / repo, [WO_ID],   args.max_iters).get(WO_ID,   [])}
        for it in sorted(with_iters & wo_iters):
            rw = idx.get((repo, it, WITH_ID))
            r0 = idx.get((repo, it, WO_ID))
            if not rw or not r0:
                continue
            for label, r in (("with", rw), ("without", r0)):
                store = cond_vectors[label]
                for key in ["succ","tests_pass_pct","pre_scc_count","post_scc_count",
                            "delta_edges","delta_scc_count","delta_nodes","delta_loc"]:
                    store.setdefault(key, []).append(r.get(key))

    def rate_bool(xs: List[Optional[bool]]) -> Optional[float]:
        vals = [x for x in xs if isinstance(x, bool)]
        if not vals:
            return None
        return 100.0 * sum(1 for v in vals if v) / len(vals)

    def prop_true(xs: List[Optional[bool]]) -> Optional[float]:
        vals = [x for x in xs if isinstance(x, bool)]
        if not vals:
            return None
        return 100.0 * sum(1 for x in vals if x) / len(vals)

    def newcycle_rate(pre_counts: List[Optional[float]], post_counts: List[Optional[float]]) -> Optional[float]:
        flags: List[Optional[bool]] = []
        for a, b in zip(pre_counts, post_counts):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                flags.append(bool(b > a))
            else:
                flags.append(None)
        return prop_true(flags)

    rows_with_without: List[Dict[str, Any]] = []
    for label in ["with", "without"]:
        vecs = cond_vectors.get(label, {})
        row = {
            "Condition": label,
            "Success%": round(rate_bool(vecs.get("succ", [])) , 2) if rate_bool(vecs.get("succ", [])) is not None else None,
            "Tests%": round(mean_or_none(vecs.get("tests_pass_pct", [])), 2) if mean_or_none(vecs.get("tests_pass_pct", [])) is not None else None,
            "NewCycle%": round(newcycle_rate(vecs.get("pre_scc_count", []), vecs.get("post_scc_count", [])), 2) if newcycle_rate(vecs.get("pre_scc_count", []), vecs.get("post_scc_count", [])) is not None else None,
            "ΔEdges": mean_or_none(vecs.get("delta_edges", [])),
            "ΔSCCcount": mean_or_none(vecs.get("delta_scc_count", [])),
            "ΔNodes": mean_or_none(vecs.get("delta_nodes", [])),
            "ΔLOC": mean_or_none(vecs.get("delta_loc", [])),
        }
        rows_with_without.append(row)

    # ---------- Write WITH vs WITHOUT (two rows) ----------
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

if __name__ == "__main__":
    main()
