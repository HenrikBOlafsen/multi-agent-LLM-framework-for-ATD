#!/usr/bin/env python3
"""
RQ1: Effect of evidence-linked explanations on refactoring success.

Outputs:
  - rq1_per_target.csv
  - rq1_overview.csv
  - rq1_per_project.csv
"""

import argparse, csv, math, statistics, sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from rq_utils import (
    read_json, read_repos_file, parse_fix_branch, list_variant_iters,
    ATD_METRICS, ATD_MODULE_CYCLES, CQ_METRICS,
    get_scc_metrics, count_repr_cycles, get_tests_pass_percent,
    scan_patch_cost, is_num, fmt, cliffs_delta, wilcoxon_paired, mcnemar_p, cohen_h,
)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--repos-file", default="repos.txt")
    ap.add_argument("--exp-with", default="expA")
    ap.add_argument("--exp-without", default="expA_without_explanation")
    ap.add_argument("--max-iters", type=int, default=5)
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    root = Path(args.results_root)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    repos = read_repos_file(Path(args.repos_file))
    if not repos:
        print(f"ERROR: no repos in {args.repos_file}", file=sys.stderr); sys.exit(1)

    per_rows: List[Dict[str, Any]] = []

    for repo, baseline_branch, _src_rel in repos:
        repo_dir = root / repo
        if not repo_dir.exists():
            print(f"[WARN] missing repo dir: {repo_dir}", file=sys.stderr); continue

        base_atd = read_json(repo_dir / baseline_branch / ATD_METRICS)
        base_mod = read_json(repo_dir / baseline_branch / ATD_MODULE_CYCLES)
        base_sum = read_json(repo_dir / baseline_branch / CQ_METRICS)
        pre_scc = get_scc_metrics(base_atd)
        pre_repr = count_repr_cycles(base_mod)

        per_variant = list_variant_iters(repo_dir, [args.exp_with, args.exp_without], args.max_iters)

        for variant, items in per_variant.items():
            prev_atd = base_atd
            prev_mod = base_mod
            for it, bdir in items:
                post_atd = read_json(bdir / ATD_METRICS)
                post_mod = read_json(bdir / ATD_MODULE_CYCLES)
                post_sum = read_json(bdir / CQ_METRICS)

                tests_pass = get_tests_pass_percent(post_sum)
                scc_pre = get_scc_metrics(prev_atd)
                scc_post = get_scc_metrics(post_atd)
                repr_pre = count_repr_cycles(prev_mod)
                repr_post = count_repr_cycles(post_mod)

                def d(key):
                    a = scc_pre.get(key); b = scc_post.get(key)
                    if not is_num(a) or not is_num(b): return None
                    return b - a

                patch_loc, files_changed = scan_patch_cost(bdir)

                succ = None
                if repr_pre is not None and repr_post is not None:
                    succ = (repr_post < repr_pre) and (scc_post["scc_count"] is not None and scc_pre["scc_count"] is not None and scc_post["scc_count"] <= scc_pre["scc_count"]) \
                           and (tests_pass is not None and tests_pass >= 99.99)

                per_rows.append({
                    "repo": repo, "variant": variant, "iter": it, "post_branch": bdir.name,
                    "pre_scc_count": scc_pre["scc_count"], "post_scc_count": scc_post["scc_count"],
                    "pre_max_scc_size": scc_pre["max_scc_size"], "post_max_scc_size": scc_post["max_scc_size"],
                    "pre_avg_scc_size": scc_pre["avg_scc_size"], "post_avg_scc_size": scc_post["avg_scc_size"],
                    "pre_nodes_in_sccs": scc_pre["total_nodes_in_cyclic_sccs"], "post_nodes_in_sccs": scc_post["total_nodes_in_cyclic_sccs"],
                    "pre_loc_in_sccs": scc_pre["total_loc_in_cyclic_sccs"], "post_loc_in_sccs": scc_post["total_loc_in_cyclic_sccs"],
                    "pre_cycle_pressure": scc_pre["cycle_pressure_lb"], "post_cycle_pressure": scc_post["cycle_pressure_lb"],
                    "pre_repr_cycles": repr_pre, "post_repr_cycles": repr_post,
                    "delta_scc_count": d("scc_count"),
                    "delta_max_scc_size": d("max_scc_size"),
                    "delta_avg_scc_size": d("avg_scc_size"),
                    "delta_nodes_in_sccs": d("total_nodes_in_cyclic_sccs"),
                    "delta_loc_in_sccs": d("total_loc_in_cyclic_sccs"),
                    "delta_cycle_pressure": d("cycle_pressure_lb"),
                    "tests_pass_pct": tests_pass,
                    "success": succ,
                    "new_cycle": (scc_post["scc_count"] > scc_pre["scc_count"]) if (isinstance(scc_post["scc_count"], int) and isinstance(scc_pre["scc_count"], int)) else None,
                    "patch_loc": patch_loc, "files_changed": files_changed,
                })
                prev_atd, prev_mod = post_atd, post_mod

    # --------- write rq1_per_target.csv ---------
    per_path = outdir / "rq1_per_target.csv"
    if per_rows:
        fields = [
            "repo","variant","iter","post_branch",
            "pre_scc_count","post_scc_count",
            "pre_max_scc_size","post_max_scc_size",
            "pre_avg_scc_size","post_avg_scc_size",
            "pre_nodes_in_sccs","post_nodes_in_sccs",
            "pre_loc_in_sccs","post_loc_in_sccs",
            "pre_cycle_pressure","post_cycle_pressure",
            "pre_repr_cycles","post_repr_cycles",
            "delta_scc_count","delta_max_scc_size","delta_avg_scc_size",
            "delta_nodes_in_sccs","delta_loc_in_sccs","delta_cycle_pressure",
            "tests_pass_pct","success","new_cycle",
            "patch_loc","files_changed"
        ]
        with per_path.open("w", newline="", encoding="utf-8") as f:
            import csv; w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in per_rows: w.writerow(r)
        print(f"Wrote: {per_path}")
    else:
        print("[WARN] No per-target rows produced", file=sys.stderr)

    # --------- aggregate: rq1_overview.csv ---------
    by_key: Dict[Tuple[str,int], Dict[str, Dict[str, Any]]] = {}
    for r in per_rows:
        key = (r["repo"], r["iter"])
        by_key.setdefault(key, {}); by_key[key][r["variant"]] = r

    exp_with = args.exp_with; exp_without = args.exp_without
    paired_keys = [k for k, vv in by_key.items() if exp_with in vv and exp_without in vv]

    succ_with, succ_without, new_with, new_without = [], [], [], []
    tests_with, tests_without = [], []

    d_metrics = [
        ("delta_scc_count", "ΔSCCcount (− better)"),
        ("delta_max_scc_size", "ΔSCCsize (max, − better)"),
        ("delta_nodes_in_sccs", "ΔNodes in SCCs (− better)"),
        ("delta_loc_in_sccs", "ΔLOC in SCCs (− better)"),
        ("delta_cycle_pressure", "ΔCyclePressure (− better)"),
        ("patch_loc", "Patch LOC (med/mean)"),
        ("files_changed", "Files changed (med/mean)"),
    ]
    vec_with = {k: [] for k,_ in d_metrics}
    vec_without = {k: [] for k,_ in d_metrics}

    for key in paired_keys:
        rw = by_key[key][exp_with]; r0 = by_key[key][exp_without]
        if isinstance(rw.get("success"), bool) and isinstance(r0.get("success"), bool):
            succ_with.append(1 if rw["success"] else 0)
            succ_without.append(1 if r0["success"] else 0)
        if isinstance(rw.get("new_cycle"), bool) and isinstance(r0.get("new_cycle"), bool):
            new_with.append(1 if rw["new_cycle"] else 0)
            new_without.append(1 if r0["new_cycle"] else 0)
        tw = rw.get("tests_pass_pct"); t0 = r0.get("tests_pass_pct")
        if is_num(tw) and is_num(t0):
            tests_with.append(float(tw)); tests_without.append(float(t0))
        for keym, _lab in d_metrics:
            vw = rw.get(keym); v0 = r0.get(keym)
            if is_num(vw) and is_num(v0):
                vec_with[keym].append(float(vw)); vec_without[keym].append(float(v0))

    def pct(x: List[int]) -> Optional[float]:
        return (100.0 * sum(x)/len(x)) if x else None

    b = c = 0
    for a, d in zip(succ_with, succ_without):
        if a == 1 and d == 0: b += 1
        elif a == 0 and d == 1: c += 1
    p_mcnemar = mcnemar_p(b, c)

    succ_p_with = pct(succ_with); succ_p_without = pct(succ_without)
    new_p_with = pct(new_with);   new_p_without = pct(new_without)
    test_mean_with = statistics.mean(tests_with) if tests_with else None
    test_mean_without = statistics.mean(tests_without) if tests_without else None
    h_succ = cohen_h((succ_p_with or 0)/100.0, (succ_p_without or 0)/100.0) if (succ_p_with is not None and succ_p_without is not None) else None

    overview_rows = []
    for keym, label in d_metrics:
        xs = vec_with[keym]; ys = vec_without[keym]
        mean_w = statistics.mean(xs) if xs else None
        sd_w   = statistics.pstdev(xs) if len(xs) > 1 else (0.0 if xs else None)
        mean_0 = statistics.mean(ys) if ys else None
        sd_0   = statistics.pstdev(ys) if len(ys) > 1 else (0.0 if ys else None)
        p_wil  = wilcoxon_paired(xs, ys) if xs and ys and len(xs) == len(ys) else None
        delta  = cliffs_delta(xs, ys) if xs and ys else None
        overview_rows.append({
            "metric": label,
            "with_mean": fmt(mean_w), "with_sd": fmt(sd_w),
            "without_mean": fmt(mean_0), "without_sd": fmt(sd_0),
            "p_wilcoxon": fmt(p_wil, 4), "cliffs_delta": fmt(delta, 4),
            "n_paired": len(xs),
        })

    over_path = outdir / "rq1_overview.csv"
    headline = {
        "Success% (with)": fmt(succ_p_with),
        "Success% (without)": fmt(succ_p_without),
        "Cohen_h (succ%)": fmt(h_succ, 4),
        "McNemar_p": fmt(p_mcnemar, 4),
        "NewCycle% (with)": fmt(new_p_with),
        "NewCycle% (without)": fmt(new_p_without),
        "Tests% mean (with)": fmt(test_mean_with),
        "Tests% mean (without)": fmt(test_mean_without),
        "Paired_targets": len(paired_keys),
    }
    with over_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(headline.keys())); w.writeheader(); w.writerow(headline)
    with over_path.open("a", newline="", encoding="utf-8") as f:
        f.write("\n")
        fields = ["metric","with_mean","with_sd","without_mean","without_sd","p_wilcoxon","cliffs_delta","n_paired"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in overview_rows: w.writerow(r)
    print(f"Wrote: {over_path}")

    # --------- rq1_per_project.csv ---------
    per_project_rows = []
    repo_keys: Dict[str, List[Tuple[str,int]]] = {}
    for r in per_rows:
        repo_keys.setdefault(r["repo"], []).append((r["repo"], r["iter"]))
    # pair by (repo, iter)
    by_key: Dict[Tuple[str,int], Dict[str, Dict[str, Any]]] = {}
    for r in per_rows:
        key = (r["repo"], r["iter"])
        by_key.setdefault(key, {}); by_key[key][r["variant"]] = r
    paired_keys = [k for k, vv in by_key.items() if exp_with in vv and exp_without in vv]

    # group by repo
    by_repo: Dict[str, List[Tuple[str,int]]] = {}
    for k in paired_keys:
        by_repo.setdefault(k[0], []).append(k)

    for repo_name, keys in by_repo.items():
        ws = []; w_new = []
        zs = []; z_new = []
        w_deltas = {"delta_scc_count":[], "delta_max_scc_size":[], "delta_cycle_pressure":[], "patch_loc":[]}
        z_deltas = {"delta_scc_count":[], "delta_max_scc_size":[], "delta_cycle_pressure":[], "patch_loc":[]}
        for k in keys:
            rw = by_key[k][exp_with]; r0 = by_key[k][exp_without]
            if isinstance(rw.get("success"), bool): ws.append(1 if rw["success"] else 0)
            if isinstance(r0.get("success"), bool): zs.append(1 if r0["success"] else 0)
            if isinstance(rw.get("new_cycle"), bool): w_new.append(1 if rw["new_cycle"] else 0)
            if isinstance(r0.get("new_cycle"), bool): z_new.append(1 if r0["new_cycle"] else 0)
            for dm in w_deltas.keys():
                if is_num(rw.get(dm)): w_deltas[dm].append(float(rw[dm]))
                if is_num(r0.get(dm)): z_deltas[dm].append(float(r0[dm]))
        def med(v): return statistics.median(v) if v else None
        row = {
            "Project": repo_name,
            "Success%with": fmt(100.0*sum(ws)/len(ws) if ws else None),
            "Success%no": fmt(100.0*sum(zs)/len(zs) if zs else None),
            "ΔSuccess(pp)": fmt((100.0*sum(ws)/len(ws) - 100.0*sum(zs)/len(zs)) if (ws and zs) else None),
            "ΔSCCcount_med(with)": fmt(med(w_deltas["delta_scc_count"])),
            "ΔSCCcount_med(no)": fmt(med(z_deltas["delta_scc_count"])),
            "ΔSCCsize_med(with)": fmt(med(w_deltas["delta_max_scc_size"])),
            "ΔSCCsize_med(no)": fmt(med(z_deltas["delta_max_scc_size"])),
            "ΔCyclePressure_med(with)": fmt(med(w_deltas["delta_cycle_pressure"])),
            "ΔCyclePressure_med(no)": fmt(med(z_deltas["delta_cycle_pressure"])),
            "PatchLOC_med(with)": fmt(med(w_deltas["patch_loc"])),
            "PatchLOC_med(no)": fmt(med(z_deltas["patch_loc"])),
        }
        per_project_rows.append(row)

    proj_path = outdir / "rq1_per_project.csv"
    if per_project_rows:
        fields = list(per_project_rows[0].keys())
        with proj_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in per_project_rows: w.writerow(r)
        print(f"Wrote: {proj_path}")
    else:
        print("[WARN] No per-project rows produced", file=sys.stderr)

if __name__ == "__main__":
    main()
