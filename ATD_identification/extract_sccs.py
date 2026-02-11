#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def count_loc(abs_path: str) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def scc_edge_objects(Gscc: nx.DiGraph, relation: str) -> List[Dict[str, Any]]:
    edges = [{"source": u, "target": v, "relation": relation} for u, v in Gscc.edges()]
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges


def edge_surplus_lb_undirected(Gscc: nx.DiGraph) -> int:
    """
    Lower bound on number of edges to remove to break cycles (undirected):
      m_und - (n-1)
    """
    n = Gscc.number_of_nodes()
    if n <= 1:
        return 0
    m_und = Gscc.to_undirected(as_view=True).number_of_edges()
    return max(0, m_und - (n - 1))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract SCCs and metrics from canonical dependency_graph.json (NO representative cycles). "
                    "Also computes global PageRank on the full graph and stores it as node_features."
    )
    ap.add_argument("dependency_graph_json", help="Path to dependency_graph.json")
    ap.add_argument("--out", required=True, help="Output path for scc_report.json")
    ap.add_argument("--pagerank-alpha", type=float, default=0.85, help="PageRank alpha (default 0.85)")
    ap.add_argument("--pagerank-max-iter", type=int, default=100, help="PageRank max iterations (default 100)")
    ap.add_argument("--pagerank-tol", type=float, default=1e-6, help="PageRank tolerance (default 1e-6)")
    args = ap.parse_args()

    dep_path = Path(args.dependency_graph_json)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(dep_path.read_text(encoding="utf-8"))
    schema_version = int(data.get("schema_version", 1))
    language = str(data.get("language", ""))
    repo_root = str(data.get("repo_root", ""))
    entry = str(data.get("entry", ""))

    nodes = data.get("nodes") or []
    edges = data.get("edges") or []

    relation = "import"
    if edges and isinstance(edges, list) and isinstance(edges[0], dict):
        relation = edges[0].get("relation", relation) or relation

    abs_by_id: Dict[str, str] = {n["id"]: str(n.get("abs_path", "")) for n in nodes if "id" in n}

    # Build full graph
    G = nx.DiGraph()
    for n in nodes:
        nid = str(n["id"])
        G.add_node(nid, abs_path=str(n.get("abs_path", "")))

    for e in edges:
        s = str(e["source"])
        t = str(e["target"])
        if s != t:
            G.add_edge(s, t, relation=str(e.get("relation", relation)))

    # Global PageRank (full graph)
    node_pagerank: Dict[str, float] = {}
    if G.number_of_nodes() > 0 and G.number_of_edges() > 0:
        try:
            node_pagerank = nx.pagerank(
                G,
                alpha=float(args.pagerank_alpha),
                max_iter=int(args.pagerank_max_iter),
                tol=float(args.pagerank_tol),
            )
        except Exception:
            node_pagerank = {}
    else:
        node_pagerank = {}

    # SCCs (cyclic only)
    scc_sets = [set(s) for s in nx.strongly_connected_components(G) if len(s) > 1]
    scc_sets.sort(key=lambda s: (len(s), sorted(s)), reverse=True)

    report_sccs: List[Dict[str, Any]] = []
    totals_nodes = 0
    totals_edges = 0
    totals_loc = 0
    cycle_pressure_lb = 0

    # LOC cache
    loc_cache: Dict[str, int] = {}

    for idx, scc in enumerate(scc_sets):
        sub = G.subgraph(scc).copy()
        n = sub.number_of_nodes()
        m = sub.number_of_edges()

        dens = m / (n * (n - 1)) if n > 1 else 0.0
        surplus = edge_surplus_lb_undirected(sub)

        loc = 0
        for u in sub.nodes():
            apath = sub.nodes[u].get("abs_path") or abs_by_id.get(u, "")
            if apath not in loc_cache:
                loc_cache[apath] = count_loc(apath)
            loc += loc_cache[apath]

        cycle_pressure_lb += surplus
        totals_nodes += n
        totals_edges += m
        totals_loc += loc

        node_list = sorted(sub.nodes())
        report_sccs.append(
            {
                "id": f"scc_{idx}",
                "size": n,
                "edge_count": m,
                "density_directed": round(dens, 6),
                "edge_surplus_lb": surplus,
                "total_loc": loc,
                "avg_loc_per_node": round(loc / n, 2) if n else 0.0,
                "nodes": [{"id": nid, "kind": "file"} for nid in node_list],
                "edges": scc_edge_objects(sub, relation),
                # NOTE: representative_cycles intentionally removed
            }
        )

    sizes = [s["size"] for s in report_sccs]
    global_metrics = {
        "scc_count": len(report_sccs),
        "total_nodes_in_cyclic_sccs": totals_nodes,
        "total_edges_in_cyclic_sccs": totals_edges,
        "total_loc_in_cyclic_sccs": totals_loc,
        "max_scc_size": max(sizes) if sizes else 0,
        "avg_scc_size": round(sum(sizes) / len(sizes), 3) if sizes else 0.0,
        "cycle_pressure_lb": cycle_pressure_lb,
    }

    # node_features: currently only pagerank (but extensible)
    node_features: Dict[str, Dict[str, Any]] = {}
    for nid in G.nodes():
        node_features[nid] = {
            "pagerank": float(node_pagerank.get(nid, 0.0)),
        }

    payload = {
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "input": {
            "schema_version": schema_version,
            "dependency_graph": str(dep_path),
            "language": language,
            "repo_root": repo_root,
            "entry": entry,
        },
        "graph": {
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
        },
        "params": {
            "pagerank_alpha": args.pagerank_alpha,
            "pagerank_max_iter": args.pagerank_max_iter,
            "pagerank_tol": args.pagerank_tol,
        },
        "global_metrics": global_metrics,
        "node_features": node_features,
        "sccs": report_sccs,
    }

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote SCC report: {out_path}")
    print(f"  sccs={len(report_sccs)} nodes={G.number_of_nodes()} edges={G.number_of_edges()}")


if __name__ == "__main__":
    main()
