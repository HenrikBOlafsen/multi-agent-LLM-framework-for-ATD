#!/usr/bin/env python3
"""
RQ2 (iterationless): Code quality for baseline vs WITH vs WITHOUT explanations.

Outputs (ONLY): rq2_trace.csv
"""

from __future__ import annotations
import argparse, csv, sys
from pathlib import Path
from typing import Dict, Any, List

from rq_utils import (
    read_json, read_repos_file,
    CQ_METRICS, extract_quality_metrics,
    parse_cycles, branch_for,
)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", required=True)
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--cycles-file", required=True)
    ap.add_argument("--exp-with", required=True)
    ap.add_argument("--exp-without", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    root = Path(args.results_root)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    repos_list = read_repos_file(Path(args.repos_file))
    if not repos_list:
        print(f"ERROR: no repos in {args.repos_file}", file=sys.stderr); sys.exit(1)

    cycles_map = parse_cycles(Path(args.cycles_file))

    trace_rows: List[Dict[str, Any]] = []

    for repo, baseline_branch, _src_rel in repos_list:
        repo_dir = root / repo
        if not repo_dir.exists():
            print(f"[WARN] missing repo dir: {repo_dir}", file=sys.stderr); continue

        # Baseline row
        base = read_json(repo_dir / baseline_branch / CQ_METRICS)
        if base:
            trace_rows.append({"repo": repo, "variant": "baseline", "cycle_id": "", **extract_quality_metrics(base)})
        else:
            print(f"[WARN] baseline metrics missing: {repo_dir / baseline_branch / CQ_METRICS}", file=sys.stderr)

        # Per-cycle rows
        cids = cycles_map.get((repo, baseline_branch), [])
        for cid in cids:
            for variant_label, exp_label in (("with", args.exp_with), ("without", args.exp_without)):
                branch = branch_for(exp_label, cid)
                j = read_json(repo_dir / branch / CQ_METRICS)
                if not j:
                    print(f"[INFO] missing metrics for {repo}@{branch} ({variant_label}, {cid})", file=sys.stderr)
                    continue
                trace_rows.append({"repo": repo, "variant": variant_label, "cycle_id": cid, **extract_quality_metrics(j)})

    # Write
    trace_path = outdir / "rq2_trace.csv"
    if trace_rows:
        fields = ["repo","variant","cycle_id","ruff_issues","mi_avg","d_rank_funcs","pyexam_arch_weighted","test_pass_pct","bandit_high"]
        with trace_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in trace_rows: w.writerow(r)
        print(f"Wrote: {trace_path}")
    else:
        print("[WARN] No trace rows produced", file=sys.stderr)

if __name__ == "__main__":
    main()
