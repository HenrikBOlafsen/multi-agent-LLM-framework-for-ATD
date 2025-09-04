#!/usr/bin/env python3
from __future__ import annotations

import json
import argparse
from sdsm_utils import PROFILES, parse_edge_kinds, build_graph_from_sdsm, scc_metrics

def run(module_sdsm_json: str, out_path: str, include_tests: bool, edge_kinds: set[str]):
    G = build_graph_from_sdsm(module_sdsm_json, include_tests=include_tests, edge_kinds=edge_kinds)
    res = scc_metrics(G)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"SCC metrics written to: {out_path}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compute SCC metrics from Depends SDSM (module-level).")
    ap.add_argument("module_sdsm_json", help="Depends SDSM JSON (module-level)")
    ap.add_argument("out_json", help="Output metrics JSON")
    ap.add_argument("--include-tests", action="store_true", help="Include test/ and tests/ files")
    ap.add_argument("--edge-profile", choices=sorted(PROFILES), default="import",
                    help="Edge-kind profile (default: import)")
    ap.add_argument("--edge-kinds", default="", help="Comma-separated kinds to override profile")
    args = ap.parse_args()

    kinds = parse_edge_kinds(args.edge_profile, args.edge_kinds)
    run(args.module_sdsm_json, args.out_json, include_tests=args.include_tests, edge_kinds=kinds)
