#!/usr/bin/env python3
"""
RQ2: Code quality before vs after (and WITH vs WITHOUT explanations).

Outputs:
  - rq2_trace.csv
  - rq2A_final.csv
  - rq2B_delta.csv
"""

import argparse, csv, math, statistics, sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from rq_utils import (
    read_json, read_repos_file, parse_fix_branch, list_variant_iters,
    CQ_METRICS, extract_quality_metrics, is_num, safe_pct_delta, fmt,
    cliffs_delta, wilcoxon_paired,
)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--repos-file", default="repos.txt")
    ap.add_argument("--exp-with", default="expA")
    ap.add_argument("--exp-without", default="expA_without_explanation")
    ap.add_argument("--max-iters", type=int, default=5)
    ap.add_argument("--aggregate", choices=["final","mean"], default="final")
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    root = Path(args.results_root)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    variants = [args.exp_with, args.exp_without]
    repos_list = read_repos_file(Path(args.repos_file))
    if not repos_list:
        print(f"ERROR: no repos in {args.repos_file}", file=sys.stderr); sys.exit(1)

    trace_rows: List[Dict[str, Any]] = []
    rq2a_rows: List[Dict[str, Any]] = []
    deltas_rows: List[Dict[str, Any]] = []

    for repo, baseline_branch, _src_rel in repos_list:
        repo_dir = root / repo
        if not repo_dir.exists():
            print(f"[WARN] missing repo dir: {repo_dir}", file=sys.stderr); continue

        base = read_json(repo_dir / baseline_branch / CQ_METRICS)
        if not base:
            print(f"[WARN] baseline metrics missing: {repo_dir / baseline_branch / CQ_METRICS}", file=sys.stderr)
            continue
        base_metrics = extract_quality_metrics(base)
        trace_rows.append({"repo": repo, "variant": "baseline", "iter": 0, **base_metrics})

        per_variant = list_variant_iters(repo_dir, variants, args.max_iters)
        for variant, items in per_variant.items():
            iter_metrics: List[Tuple[int, Dict[str, Any]]] = []
            for it, bdir in items:
                s = read_json(bdir / CQ_METRICS)
                if not s: continue
                iter_metrics.append((it, extract_quality_metrics(s)))

            if not iter_metrics:
                print(f"[INFO] no iterations for {repo} variant={variant}", file=sys.stderr)
                continue

            iter_metrics.sort(key=lambda x: x[0])
            for it, m in iter_metrics:
                trace_rows.append({"repo": repo, "variant": variant, "iter": it, **m})

            if args.aggregate == "final":
                agg_iter = iter_metrics[-1][0]
                agg_metrics = iter_metrics[-1][1]
            else:
                numeric_keys = ["ruff_issues","mi_avg","d_rank_funcs","pyexam_arch_weighted","test_pass_pct","bandit_high"]
                sums = {k: 0.0 for k in numeric_keys}
                counts = {k: 0 for k in numeric_keys}
                for _, m in iter_metrics:
                    for k in numeric_keys:
                        v = m.get(k)
                        if is_num(v):
                            sums[k] += float(v); counts[k] += 1
                agg_metrics = {k: (sums[k]/counts[k] if counts[k] else None) for k in numeric_keys}
                agg_iter = f"mean(1..{iter_metrics[-1][0]})"

            rq2a_rows.append({"repo": repo, "variant": variant, "iter_agg": agg_iter, **agg_metrics})

            def diff(a, b):
                if a is None or b is None: return None
                return b - a

            deltas_rows.append({
                "repo": repo, "variant": variant,
                "ruff_issues_delta": diff(base_metrics.get("ruff_issues"), agg_metrics.get("ruff_issues")),
                "ruff_issues_pct": safe_pct_delta(base_metrics.get("ruff_issues"), agg_metrics.get("ruff_issues")),
                "mi_avg_delta": diff(base_metrics.get("mi_avg"), agg_metrics.get("mi_avg")),
                "d_rank_funcs_delta": diff(base_metrics.get("d_rank_funcs"), agg_metrics.get("d_rank_funcs")),
                "pyexam_arch_weighted_delta": diff(base_metrics.get("pyexam_arch_weighted"), agg_metrics.get("pyexam_arch_weighted")),
                "bandit_high_delta": diff(base_metrics.get("bandit_high"), agg_metrics.get("bandit_high")),
                "test_pass_pct_final": agg_metrics.get("test_pass_pct"),
            })

    # trace
    trace_path = outdir / "rq2_trace.csv"
    if trace_rows:
        fields = ["repo","variant","iter","ruff_issues","mi_avg","d_rank_funcs","pyexam_arch_weighted","test_pass_pct","bandit_high"]
        with trace_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in trace_rows: w.writerow(r)
        print(f"Wrote: {trace_path}")
    else:
        print("[WARN] No trace rows produced", file=sys.stderr)

    # RQ2-A
    rq2a_path = outdir / "rq2A_final.csv"
    if rq2a_rows:
        fields = ["repo","variant","iter_agg","ruff_issues","mi_avg","d_rank_funcs","pyexam_arch_weighted","test_pass_pct","bandit_high"]
        with rq2a_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in rq2a_rows: w.writerow(r)
        print(f"Wrote: {rq2a_path}")
    else:
        print("[WARN] No RQ2-A rows produced", file=sys.stderr)

    # RQ2-B
    rq2b_path = outdir / "rq2B_delta.csv"
    if deltas_rows:
        by_variant: Dict[str, List[Dict[str, Any]]] = {}
        for r in deltas_rows: by_variant.setdefault(r["variant"], []).append(r)

        metrics = [
            ("ruff_issues_pct", "% Δ Ruff (− better)"),
            ("mi_avg_delta", "Δ MI avg (+ better)"),
            ("d_rank_funcs_delta", "Δ D-rank funcs (− better)"),
            ("pyexam_arch_weighted_delta", "Δ Architectural (weighted) (− better)"),
            ("bandit_high_delta", "Δ Bandit High (− better)"),
            ("test_pass_pct_final", "Final test pass % (higher better)"),
        ]
        with_rows = by_variant.get(args.exp_with, [])
        without_rows = by_variant.get(args.exp_without, [])

        def repo_map(rows, key):
            return {r["repo"]: r.get(key) for r in rows if is_num(r.get(key))}

        out_rows = []
        for key, label in metrics:
            def agg_mean_sd(rows: List[Dict[str, Any]], k: str):
                vals = [r.get(k) for r in rows if is_num(r.get(k))]
                if not vals: return (None, None, 0)
                if len(vals) == 1: return (float(vals[0]), 0.0, 1)
                return (statistics.mean(vals), statistics.pstdev(vals), len(vals))

            with_mean, with_sd, n_with = agg_mean_sd(with_rows, key)
            without_mean, without_sd, n_without = agg_mean_sd(without_rows, key)
            rel = None
            if is_num(without_mean) and without_mean != 0 and is_num(with_mean):
                rel = 100.0 * (with_mean - without_mean) / abs(without_mean)

            wm = repo_map(with_rows, key); wom = repo_map(without_rows, key)
            common = sorted(set(wm.keys()) & set(wom.keys()))
            x = [float(wm[r]) for r in common]; y = [float(wom[r]) for r in common]
            p = wilcoxon_paired(x, y)
            delta = cliffs_delta(x, y) if x and y else None

            out_rows.append({
                "metric": label,
                "with_mean": "" if with_mean is None else f"{with_mean:.2f}",
                "with_sd": "" if with_sd is None else f"{with_sd:.2f}",
                "without_mean": "" if without_mean is None else f"{without_mean:.2f}",
                "without_sd": "" if without_sd is None else f"{without_sd:.2f}",
                "relative_improvement_pct": "" if rel is None else f"{rel:.2f}",
                "n_with": n_with, "n_without": n_without, "n_paired": len(common),
                "p_wilcoxon": fmt(p, 4), "cliffs_delta": fmt(delta, 4),
            })

        fields = ["metric","with_mean","with_sd","without_mean","without_sd",
                  "relative_improvement_pct","n_with","n_without","n_paired",
                  "p_wilcoxon","cliffs_delta"]
        with rq2b_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in out_rows: w.writerow(r)
        print(f"Wrote: {rq2b_path}")
    else:
        print("[WARN] No delta rows produced", file=sys.stderr)

if __name__ == "__main__":
    main()
