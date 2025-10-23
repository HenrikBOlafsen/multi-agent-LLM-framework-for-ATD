#!/usr/bin/env python3
from __future__ import annotations
import os, json, argparse
from pydeps_utils import build_graph_from_pydeps, scc_metrics

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compute SCC/global metrics from pydeps JSON.")
    ap.add_argument("pydeps_json", help="pydeps intermediate JSON (deps-output)")
    ap.add_argument("output_json", nargs="?", default="ATD_metrics.json", help="Output JSON path")
    args = ap.parse_args()

    repo_root = os.getenv("REPO_ROOT", os.getcwd())
    G = build_graph_from_pydeps(args.pydeps_json, repo_root=repo_root)
    metrics = scc_metrics(G)

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"Wrote metrics to: {args.output_json}")
