#!/usr/bin/env python3
"""
RQ2 table generator — multi-root, success-filtered deltas vs baseline.

Marker support:
- If a branch dir contains `.copied_metrics_marker`, we treat it as "no changes":
  post metrics are recorded as baseline metrics in the trace (so deltas are 0 downstream).

Outputs:
  - rq2_trace.csv                 (raw tool metrics per variant; baseline/with/without)
  - rq2_success_deltas.csv        (per-run deltas vs baseline for success-only)
  - rq2_overall.csv               (aggregated deltas across all projects, WITH vs WITHOUT + p-values)
  - rq2_per_project.csv           (aggregated deltas per project, WITH vs WITHOUT)
"""
from __future__ import annotations
import argparse, csv, sys, math
from pathlib import Path
from typing import Dict, Any, List, Tuple

from rq_utils import (
    read_json, read_repos_file, CQ_METRICS, extract_quality_metrics,
    parse_cycles, branch_for, map_roots_exps
)

# -------------- helpers --------------
METRICS = ["ruff_issues","mi_avg","d_rank_funcs","pyexam_arch_weighted","bandit_high","test_pass_pct"]
DELTA_NAMES = {m: f"Δ{m}" for m in METRICS}

def mean_std(xs: List[float]) -> Tuple[float, float]:
    if not xs:
        return (float("nan"), float("nan"))
    m = sum(xs)/len(xs)
    if len(xs) < 2:
        return (m, float("nan"))
    v = sum((x-m)*(x-m) for x in xs)/(len(xs)-1)
    return (m, v**0.5)

def wilcoxon_signed(x: List[float], y: List[float]) -> float:
    try:
        from scipy.stats import wilcoxon
        if len(x) == len(y) and len(x) > 0:
            stat, p = wilcoxon(x, y, zero_method="wilcox", correction=False, alternative="two-sided", mode="auto")
            return float(p)
        return float("nan")
    except Exception:
        return float("nan")

def iqr(xs: List[float]) -> float:
    if not xs: return float("nan")
    xs2 = sorted(xs)
    n = len(xs2)
    def pct(p):
        k = (n-1)*p
        f = math.floor(k); c = math.ceil(k)
        if f == c: return xs2[int(k)]
        return xs2[f] + (xs2[c]-xs2[f])*(k-f)
    return pct(0.75) - pct(0.25)

# -------------- main --------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-roots", nargs="+", required=True)
    ap.add_argument("--exp-ids", nargs="+", required=True)
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--cycles-file", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--rq1-per-cycle", help="Path to rq1_per_cycle.csv; defaults to <outdir>/rq1_per_cycle.csv")
    args = ap.parse_args()

    cfgs = map_roots_exps(args.results_roots, args.exp_ids)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    # -------- build trace (with marker handling) --------
    repos_list = read_repos_file(Path(args.repos_file))
    cycles_map = parse_cycles(Path(args.cycles_file))
    trace_rows: List[Dict[str, Any]] = []

    for results_root, with_id, wo_id in cfgs:
        root = Path(results_root)
        for repo, baseline_branch, _src_rel in repos_list:
            repo_dir = root / repo

            base = read_json(repo_dir / baseline_branch / CQ_METRICS)
            if base:
                trace_rows.append({
                    "repo": repo, "results_root": str(root),
                    "variant": "baseline", "exp_label": "", "cycle_id": "", **extract_quality_metrics(base)
                })

            for cid in cycles_map.get((repo, baseline_branch), []):
                for variant_label, exp_label in (("with", with_id), ("without", wo_id)):
                    branch = branch_for(exp_label, cid)
                    branch_dir = repo_dir / branch
                    # If marker exists, reuse baseline metrics.
                    use_base = (branch_dir / ".copied_metrics_marker").exists()
                    if use_base and base:
                        j = base
                    else:
                        j = read_json(branch_dir / CQ_METRICS)
                    if j:
                        trace_rows.append({
                            "repo": repo, "results_root": str(root),
                            "variant": variant_label, "exp_label": exp_label, "cycle_id": str(cid),
                            **extract_quality_metrics(j)
                        })

    # write trace
    trace_path = outdir / "rq2_trace.csv"
    if trace_rows:
        fields = ["repo","results_root","variant","exp_label","cycle_id"] + METRICS
        with trace_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in trace_rows: w.writerow({k: r.get(k) for k in fields})
        print(f"Wrote: {trace_path}")
    else:
        print("[WARN] No trace rows produced", file=sys.stderr)

    # -------- success-filtered deltas vs baseline --------
    import csv as _csv
    rq1_path = Path(args.rq1_per_cycle) if args.rq1_per_cycle else (outdir / "rq1_per_cycle.csv")
    if not rq1_path.exists():
        print(f"[WARN] RQ1 per-cycle not found: {rq1_path} — cannot compute success-filtered deltas", file=sys.stderr)
        return

    def load_csv_dicts(path: Path) -> List[Dict[str, Any]]:
        with path.open("r", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            return [dict(row) for row in reader]

    rq1_rows = load_csv_dicts(rq1_path)
    # success keys: succ == True; condition is 'with' or 'without'
    succ_keys = set()
    for r in rq1_rows:
        try:
            succ = str(r.get("succ","")).strip().lower() in ("true","1","yes")
            if not succ: continue
            repo = r.get("repo"); cid = str(r.get("cycle_id"))
            exp = r.get("exp_label") or r.get("variant_label") or ""
            cond = r.get("condition")  # with/without
            if repo and cid and cond in ("with","without"):
                succ_keys.add((repo, cid, exp, cond))
        except Exception:
            continue

    # index trace by (repo, results_root, variant, exp_label, cycle_id)
    from collections import defaultdict
    by_key = defaultdict(list)
    for r in trace_rows:
        key = (r.get("repo"), r.get("results_root"), r.get("variant"),
               r.get("exp_label",""), str(r.get("cycle_id","")))
        by_key[key].append(r)

    # baseline per (repo, results_root)
    baseline_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in trace_rows:
        if r.get("variant") == "baseline":
            baseline_map[(r["repo"], r["results_root"])] = r

    # compute success-only deltas
    deltas: List[Dict[str, Any]] = []
    for (repo, cid, exp, cond) in succ_keys:
        # find all roots that have this (repo, cid, exp, cond)
        for (r_repo, r_root, r_var, r_exp, r_cid), rows in by_key.items():
            if r_repo != repo or r_cid != cid or r_exp != exp or r_var != cond:
                continue
            run = rows[0]
            base = baseline_map.get((repo, r_root)) or baseline_map.get((repo, next(iter(baseline_map.keys()))[1]))  # fallback
            if not base:
                continue
            out = {
                "repo": repo,
                "results_root": r_root,
                "variant": cond,        # with/without
                "exp_label": exp,
                "cycle_id": cid,
            }
            for m in METRICS:
                rv = run.get(m)
                bv = base.get(m)
                try:
                    rvf = float(rv) if rv is not None and rv != "" else float("nan")
                    bvf = float(bv) if bv is not None and bv != "" else float("nan")
                    out[DELTA_NAMES[m]] = rvf - bvf
                except Exception:
                    out[DELTA_NAMES[m]] = float("nan")
            deltas.append(out)

    # write raw success deltas
    if deltas:
        delta_fields = ["repo","results_root","variant","exp_label","cycle_id"] + [DELTA_NAMES[m] for m in METRICS]
        delta_path = outdir / "rq2_success_deltas.csv"
        with delta_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=delta_fields); w.writeheader()
            for r in deltas: w.writerow(r)
        print(f"Wrote: {delta_path}")
    else:
        print("[WARN] No success-filtered deltas produced", file=sys.stderr)
        return

    # -------- aggregate: overall (WITH vs WITHOUT) + Wilcoxon --------
    import math as _math
    from collections import defaultdict

    by_cond: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in deltas:
        by_cond[r["variant"]].append(r)

    overall_rows: List[Dict[str, Any]] = []
    # mean±std for each condition
    for cond in ("without","with"):
        xs = by_cond.get(cond, [])
        row = {"Condition": cond, "n": len(xs)}
        for m in METRICS:
            vals = [float(r.get(DELTA_NAMES[m])) for r in xs if r.get(DELTA_NAMES[m]) not in (None, "", "nan")]
            vals = [v for v in vals if not (_math.isnan(v) or _math.isinf(v))]
            mu, sd = mean_std(vals)
            row[DELTA_NAMES[m] + "_mean"] = (None if _math.isnan(mu) else mu)
            row[DELTA_NAMES[m] + "_std"]  = (None if _math.isnan(sd) else sd)
        overall_rows.append(row)

    # paired p-values (WITH vs WITHOUT), aligning on (repo, cycle_id, exp_label)
    def paired_series(metric: str) -> Tuple[List[float], List[float]]:
        W = {}; WO = {}
        for r in deltas:
            key = (r["repo"], r["cycle_id"], r["exp_label"])
            v = r.get(DELTA_NAMES[metric])
            try:
                vf = float(v)
                if math.isnan(vf) or math.isinf(vf):
                    continue
            except Exception:
                continue
            if r["variant"] == "with":
                W[key] = vf
            elif r["variant"] == "without":
                WO[key] = vf
        common = sorted(set(W.keys()).intersection(WO.keys()))
        x = [W[k] for k in common]
        y = [WO[k] for k in common]
        return x, y

    stats_row = {"Condition": "stats", "n": None}
    for m in METRICS:
        x, y = paired_series(m)
        stats_row[DELTA_NAMES[m] + "_wilcoxon_p"] = wilcoxon_signed(x, y)
        stats_row[DELTA_NAMES[m] + "_pairs"] = len(x)
    overall_rows.append(stats_row)

    overall_path = outdir / "rq2_overall.csv"
    with overall_path.open("w", newline="", encoding="utf-8") as f:
        keys = []
        for r in overall_rows:
            for k in r.keys():
                if k not in keys: keys.append(k)
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
        for r in overall_rows: w.writerow(r)
    print(f"Wrote: {overall_path}")

    # -------- aggregate: per project (WITH/WITHOUT) --------
    per_proj_rows: List[Dict[str, Any]] = []
    proj_cond: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in deltas:
        proj_cond[(r["repo"], r["variant"])].append(r)

    for (repo, cond), xs in sorted(proj_cond.items()):
        row = {"repo": repo, "Condition": cond, "n_succ": len(xs)}
        for m in METRICS:
            vals = []
            for r in xs:
                v = r.get(DELTA_NAMES[m])
                try:
                    vf = float(v)
                    if math.isnan(vf) or math.isinf(vf): continue
                    vals.append(vf)
                except Exception:
                    continue
            mu, sd = mean_std(vals)
            row[DELTA_NAMES[m] + "_mean"] = (None if math.isnan(mu) else mu)
            row[DELTA_NAMES[m] + "_std"]  = (None if math.isnan(sd) else sd)
        per_proj_rows.append(row)

    per_proj_path = outdir / "rq2_per_project.csv"
    if per_proj_rows:
        keys = list(per_proj_rows[0].keys())
        with per_proj_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
            for r in per_proj_rows: w.writerow(r)
        print(f"Wrote: {per_proj_path}")
    else:
        print("[WARN] No per-project rows produced", file=sys.stderr)

if __name__ == "__main__":
    main()
