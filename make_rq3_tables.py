#!/usr/bin/env python3
"""
RQ3: Scalability vs. cycle complexity (progress over iterations, binning, correlations).

Outputs:
  - rq3_progress.csv
  - rq3_bins.csv
  - rq3_corr.csv
"""

import argparse, csv, statistics, sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Iterable
from scipy.stats import spearmanr, wilcoxon  # used locally

from rq_utils import (
    read_json, read_repos_file, list_variant_iters,
    ATD_METRICS, ATD_MODULE_CYCLES, CQ_METRICS,
    get_scc_metrics, count_repr_cycles, get_tests_pass_percent,
    is_num, pct_reduction, fmt,
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

    progress_rows: List[Dict[str, Any]] = []
    paired_for_bins: List[Dict[str, Any]] = []

    for repo, baseline_branch, _src_rel in repos:
        repo_dir = root / repo
        if not repo_dir.exists():
            print(f"[WARN] missing repo dir: {repo_dir}", file=sys.stderr); continue

        base_atd = read_json(repo_dir / baseline_branch / ATD_METRICS)
        base_mod = read_json(repo_dir / baseline_branch / ATD_MODULE_CYCLES)
        base_sum = read_json(repo_dir / baseline_branch / CQ_METRICS)

        b_scc = get_scc_metrics(base_atd)
        b_repr = count_repr_cycles(base_mod)

        per_variant = list_variant_iters(repo_dir, [args.exp_with, args.exp_without], args.max_iters)

        for variant, items in per_variant.items():
            for it, bdir in items:
                post_atd = read_json(bdir / ATD_METRICS)
                post_mod = read_json(bdir / ATD_MODULE_CYCLES)
                post_sum = read_json(bdir / CQ_METRICS)

                cur = get_scc_metrics(post_atd)
                cur_repr = count_repr_cycles(post_mod)
                tests_pass = get_tests_pass_percent(post_sum)

                succ = None
                if b_repr is not None and cur_repr is not None and b_scc["scc_count"] is not None and cur["scc_count"] is not None:
                    succ = (cur_repr < b_repr) and (cur["scc_count"] <= b_scc["scc_count"]) and (tests_pass is not None and tests_pass >= 99.99)

                abs_row = {
                    "repo": repo, "variant": variant, "iter": it,
                    "scc_count": cur["scc_count"],
                    "nodes_in_sccs": cur["total_nodes_in_cyclic_sccs"],
                    "edges_in_sccs": cur["total_edges_in_cyclic_sccs"],
                    "loc_in_sccs": cur["total_loc_in_cyclic_sccs"],
                    "max_scc_size": cur["max_scc_size"],
                    "avg_scc_size": cur["avg_scc_size"],
                    "avg_density": cur["avg_density_directed"],
                    "cycle_pressure": cur["cycle_pressure_lb"],
                    "repr_cycles": cur_repr,
                    "tests_pass_pct": tests_pass,
                    "success": succ,
                    "base_scc_count": b_scc["scc_count"],
                    "base_nodes_in_sccs": b_scc["total_nodes_in_cyclic_sccs"],
                    "base_loc_in_sccs": b_scc["total_loc_in_cyclic_sccs"],
                    "base_max_scc_size": b_scc["max_scc_size"],
                    "base_avg_scc_size": b_scc["avg_scc_size"],
                    "base_avg_density": b_scc["avg_density_directed"],
                    "base_cycle_pressure": b_scc["cycle_pressure_lb"],
                    "base_repr_cycles": b_repr,
                }

                abs_row.update({
                    "red_scc_count_pct": pct_reduction(b_scc["scc_count"], cur["scc_count"]),
                    "red_nodes_in_sccs_pct": pct_reduction(b_scc["total_nodes_in_cyclic_sccs"], cur["total_nodes_in_cyclic_sccs"]),
                    "red_edges_in_sccs_pct": pct_reduction(b_scc["total_edges_in_cyclic_sccs"], cur["total_edges_in_cyclic_sccs"]),
                    "red_loc_in_sccs_pct": pct_reduction(b_scc["total_loc_in_cyclic_sccs"], cur["total_loc_in_cyclic_sccs"]),
                    "red_max_scc_size_pct": pct_reduction(b_scc["max_scc_size"], cur["max_scc_size"]),
                    "red_cycle_pressure_pct": pct_reduction(b_scc["cycle_pressure_lb"], cur["cycle_pressure_lb"]),
                    "red_repr_cycles_pct": pct_reduction(b_repr, cur_repr),
                })

                progress_rows.append(abs_row)
                paired_for_bins.append(abs_row)

    # progress CSV
    prog_path = outdir / "rq3_progress.csv"
    if progress_rows:
        fields = list(progress_rows[0].keys())
        with prog_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in progress_rows:
                w.writerow({k: (fmt(v) if isinstance(v, float) else v) for k,v in r.items()})
        print(f"Wrote: {prog_path}")
    else:
        print("[WARN] No progress rows produced", file=sys.stderr)

    # binning
    def bin_scc_size(x: Optional[float]) -> str:
        if not is_num(x): return "NA"
        x = int(x)
        if x <= 3: return "[1–3]"
        if x <= 10: return "[4–10]"
        if x <= 50: return "[11–50]"
        return "50+"
    def bin_density(x: Optional[float]) -> str:
        if not is_num(x): return "NA"
        if x <= 0.10: return "[0–0.10]"
        if x <= 0.30: return "(0.10–0.30]"
        return ">0.30"
    def bin_nodes(x: Optional[float]) -> str:
        if not is_num(x): return "NA"
        if x <= 20: return "[1–20]"
        if x <= 100: return "[21–100]"
        if x <= 300: return "[101–300]"
        return "300+"

    bin_rows: List[Dict[str, Any]] = []
    for dim, bin_fn, base_key in [
        ("SCC size (max)", bin_scc_size, "base_max_scc_size"),
        ("Density (avg)", bin_density, "base_avg_density"),
        ("Nodes in SCCs", bin_nodes, "base_nodes_in_sccs"),
    ]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in paired_for_bins:
            groups.setdefault(bin_fn(r.get(base_key)), []).append(r)

        for bin_label, rows in sorted(groups.items()):
            def srate(rows):
                vals = [int(r["success"]) for r in rows if isinstance(r.get("success"), bool)]
                return (100.0*sum(vals)/len(vals)) if vals else None
            def mean_of(key):
                vals = [r.get(key) for r in rows if is_num(r.get(key))]
                return statistics.mean(vals) if vals else None

            rows_w = [r for r in rows if r["variant"] == args.exp_with]
            rows_0 = [r for r in rows if r["variant"] == args.exp_without]

            overall = {
                "dimension": dim, "bin": bin_label, "n": len(rows),
                "success_overall%": srate(rows),
                "mean_red_nodes%": mean_of("red_nodes_in_sccs_pct"),
                "mean_red_loc%": mean_of("red_loc_in_sccs_pct"),
                "mean_red_max_scc%": mean_of("red_max_scc_size_pct"),
                "mean_red_cycle_pressure%": mean_of("red_cycle_pressure_pct"),
                "success_with%": srate(rows_w), "success_without%": srate(rows_0),
                "n_with": len(rows_w), "n_without": len(rows_0),
            }

            # paired wilcoxon per bin on red_loc
            def key_of(r): return (r["repo"], r["iter"])
            m_w = { key_of(r): r for r in rows_w }
            m_0 = { key_of(r): r for r in rows_0 }
            common = sorted(set(m_w.keys()) & set(m_0.keys()))
            xs = [m_w[k].get("red_loc_in_sccs_pct") for k in common if is_num(m_w[k].get("red_loc_in_sccs_pct"))]
            ys = [m_0[k].get("red_loc_in_sccs_pct") for k in common if is_num(m_0[k].get("red_loc_in_sccs_pct"))]
            p_wil = None
            if xs and ys and len(xs) == len(ys):
                try:
                    _, p_wil = wilcoxon(xs, ys, zero_method="wilcox", correction=False, alternative="two-sided", mode="auto")
                    p_wil = float(p_wil)
                except Exception:
                    p_wil = None

            overall["p_wilcoxon_red_loc"] = p_wil
            overall["n_paired"] = len(xs)
            bin_rows.append(overall)

    bins_path = outdir / "rq3_bins.csv"
    if bin_rows:
        fields = ["dimension","bin","n","n_with","n_without",
                  "success_overall%","success_with%","success_without%",
                  "mean_red_nodes%","mean_red_loc%","mean_red_max_scc%","mean_red_cycle_pressure%",
                  "p_wilcoxon_red_loc","n_paired"]
        with bins_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in bin_rows:
                out = r.copy()
                for k in ["success_overall%","success_with%","success_without%",
                          "mean_red_nodes%","mean_red_loc%","mean_red_max_scc%","mean_red_cycle_pressure%",
                          "p_wilcoxon_red_loc"]:
                    out[k] = fmt(out.get(k), 4 if "p_" in k else 2)
                w.writerow(out)
        print(f"Wrote: {bins_path}")
    else:
        print("[WARN] No bin rows produced", file=sys.stderr)

    # correlations (using final iteration per (repo, variant))
    final_rows: Dict[Tuple[str,str], Dict[str, Any]] = {}
    for r in progress_rows:
        key = (r["repo"], r["variant"])
        if key not in final_rows or r["iter"] > final_rows[key]["iter"]:
            final_rows[key] = r

    corr_rows: List[Dict[str, Any]] = []
    outcomes = [
        ("success", lambda r: 1 if r.get("success") is True else (0 if r.get("success") is False else None), "Success (binary)"),
        ("red_loc_in_sccs_pct", lambda r: r.get("red_loc_in_sccs_pct"), "% red. LOC in cycles"),
        ("red_nodes_in_sccs_pct", lambda r: r.get("red_nodes_in_sccs_pct"), "% red. Nodes in cycles"),
        ("red_max_scc_size_pct", lambda r: r.get("red_max_scc_size_pct"), "% red. Max SCC size"),
    ]
    features = [
        ("base_max_scc_size", "Baseline max SCC size"),
        ("base_avg_density", "Baseline avg density"),
        ("base_nodes_in_sccs", "Baseline nodes in SCCs"),
        ("base_loc_in_sccs", "Baseline LOC in SCCs"),
        ("base_cycle_pressure", "Baseline cycle pressure"),
        ("base_repr_cycles", "Baseline representative cycles"),
    ]

    def add_corr_block(label_suffix: str, rows_iter: Iterable[Dict[str, Any]]):
        rows_list = list(rows_iter)
        for f_key, f_label in features:
            for _o_key, o_fn, o_label in outcomes:
                xs, ys = [], []
                for r in rows_list:
                    xv = r.get(f_key); yv = o_fn(r)
                    if is_num(xv) and is_num(yv):
                        xs.append(float(xv)); ys.append(float(yv))
                rho = p = None
                if xs and ys and len(xs) > 2:
                    rho, p = spearmanr(xs, ys); rho = float(rho); p = float(p)
                corr_rows.append({
                    "subset": label_suffix, "feature": f_label, "outcome": o_label,
                    "n": len(xs), "spearman_rho": fmt(rho, 4), "p_value": fmt(p, 4),
                })

    add_corr_block("overall", final_rows.values())
    add_corr_block(f"variant={args.exp_with}", [r for k,r in final_rows.items() if k[1]==args.exp_with])
    add_corr_block(f"variant={args.exp_without}", [r for k,r in final_rows.items() if k[1]==args.exp_without])

    corr_path = outdir / "rq3_corr.csv"
    if corr_rows:
        fields = ["subset","feature","outcome","n","spearman_rho","p_value"]
        with corr_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in corr_rows: w.writerow(r)
        print(f"Wrote: {corr_path}")
    else:
        print("[WARN] No correlation rows produced", file=sys.stderr)

if __name__ == "__main__":
    main()
