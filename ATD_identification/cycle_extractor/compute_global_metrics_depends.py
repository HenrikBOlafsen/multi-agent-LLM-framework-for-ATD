from __future__ import annotations
import os, json, argparse
from sdsm_utils import build_graph_from_sdsm, scc_metrics, parse_edge_kinds_from_env

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compute SCC/global metrics from Depends SDSM.")
    ap.add_argument("sdsm_json", help="Depends SDSM JSON (module-level)")
    ap.add_argument("output_json", nargs="?", default="scc_metrics.json", help="Output JSON path")
    args = ap.parse_args()

    kinds = parse_edge_kinds_from_env(default_csv=os.getenv("EDGE_KINDS", "Import,Include,Extend,Implement,Mixin"))
    G = build_graph_from_sdsm(args.sdsm_json, edge_kinds=kinds)
    metrics = scc_metrics(G)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"Wrote metrics to: {args.output_json}")
