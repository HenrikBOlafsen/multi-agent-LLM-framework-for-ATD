#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import networkx as nx


# -------------------------
# Helpers
# -------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def count_loc(abs_path: str) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except (FileNotFoundError, IsADirectoryError):
        return 0


def canonicalize_cycle(nodes: List[str]) -> Tuple[str, ...]:
    """
    Canonicalize a cycle for de-duplication:
    - rotate to the lexicographically smallest node
    - compare forward vs reverse and pick smallest tuple
    """
    if not nodes:
        return ()
    cyc = list(nodes)
    i = min(range(len(cyc)), key=lambda j: cyc[j])
    fwd = tuple(cyc[i:] + cyc[:i])

    rc = list(reversed(cyc))
    j = min(range(len(rc)), key=lambda t: rc[t])
    rev = tuple(rc[j:] + rc[:j])

    return fwd if fwd <= rev else rev


def edges_of_cycle(nodes: List[str]) -> List[Tuple[str, str]]:
    m = len(nodes)
    return [(nodes[i], nodes[(i + 1) % m]) for i in range(m)]


def cycle_edge_objects(nodes: List[str], relation: str) -> List[Dict]:
    m = len(nodes)
    return [{"source": nodes[i], "target": nodes[(i + 1) % m], "relation": relation} for i in range(m)]


def scc_edge_objects(Gscc: nx.DiGraph, relation: str) -> List[Dict]:
    edges = [{"source": u, "target": v, "relation": relation} for u, v in Gscc.edges()]
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges


def enumerate_cycles_filtered(Gscc: nx.DiGraph, *, max_size: Optional[int]) -> List[List[str]]:
    """
    Enumerate all simple cycles (<= max_size) deterministically.
    Sort: largest-first, then lexicographically.
    """
    seen: Set[Tuple[str, ...]] = set()
    cycles: List[List[str]] = []

    for cyc in nx.simple_cycles(Gscc):
        key = canonicalize_cycle(cyc)
        if not key or key in seen:
            continue
        if max_size is not None and len(key) > max_size:
            continue
        seen.add(key)
        cycles.append(list(key))

    # Deterministic largest-first
    cycles.sort(key=lambda ns: (len(ns), tuple(ns)), reverse=True)
    return cycles


def greedy_edge_disjoint_two_pass(
    candidates: List[List[str]],
    *,
    per_size_cap: int,
    max_total: int,
) -> List[List[str]]:
    """
    Pass 1: up to per_size_cap edge-disjoint cycles for each length (largest->smallest).
    Pass 2: top up with remaining edge-disjoint cycles (largest-first).
    max_total=0 means no overall cap.
    """
    if per_size_cap <= 0:
        per_size_cap = 10**9

    picked: List[List[str]] = []
    used_edges: Set[Tuple[str, str]] = set()
    picked_keys: Set[Tuple[str, ...]] = set()

    by_len: Dict[int, List[List[str]]] = {}
    for cyc in candidates:
        by_len.setdefault(len(cyc), []).append(cyc)

    # Pass 1
    for L in sorted(by_len.keys(), reverse=True):
        taken = 0
        for cyc in by_len[L]:
            cedges = set(edges_of_cycle(cyc))
            if cedges.isdisjoint(used_edges):
                picked.append(cyc)
                used_edges.update(cedges)
                picked_keys.add(tuple(cyc))
                taken += 1
                if max_total > 0 and len(picked) >= max_total:
                    return picked
                if taken >= per_size_cap:
                    break

    # Pass 2
    for cyc in candidates:
        if tuple(cyc) in picked_keys:
            continue
        cedges = set(edges_of_cycle(cyc))
        if cedges.isdisjoint(used_edges):
            picked.append(cyc)
            used_edges.update(cedges)
            if max_total > 0 and len(picked) >= max_total:
                break

    return picked


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


# -------------------------
# Main extraction
# -------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Extract SCCs, representative cycles, and metrics from canonical dependency_graph.json")
    ap.add_argument("dependency_graph_json", help="Path to dependency_graph.json")
    ap.add_argument("--out", required=True, help="Output path for scc_report.json")
    ap.add_argument("--max-cycle-size", type=int, default=8, help="Max cycle length to consider (default: 8)")
    ap.add_argument("--per-size-cap", type=int, default=2, help="Pick up to N cycles per cycle length in pass 1 (default: 2). 0 disables balancing.")
    ap.add_argument("--max-cycles-per-scc", type=int, default=0, help="Overall cap of representative cycles per SCC (0 = no cap)")
    args = ap.parse_args()

    dep_path = Path(args.dependency_graph_json)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(dep_path.read_text(encoding="utf-8"))
    schema_version = int(data.get("schema_version", 1))
    language = data.get("language", "")
    repo_root = data.get("repo_root", "")
    entry = data.get("entry", "")
    relation = "import"

    # Build graph
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []

    abs_by_id: Dict[str, str] = {n["id"]: n.get("abs_path", "") for n in nodes if "id" in n}

    G = nx.DiGraph()
    for n in nodes:
        nid = n["id"]
        G.add_node(nid, abs_path=n.get("abs_path", ""))

    for e in edges:
        s = e["source"]
        t = e["target"]
        if s != t:
            G.add_edge(s, t, relation=e.get("relation", relation))

    # SCCs
    scc_sets = [set(s) for s in nx.strongly_connected_components(G) if len(s) > 1]
    scc_sets.sort(key=lambda s: (len(s), sorted(s)), reverse=True)

    report_sccs: List[Dict] = []

    totals_nodes = 0
    totals_edges = 0
    totals_loc = 0
    cycle_pressure_lb = 0

    for idx, scc in enumerate(scc_sets):
        sub = G.subgraph(scc).copy()
        n = sub.number_of_nodes()
        m = sub.number_of_edges()

        dens = m / (n * (n - 1)) if n > 1 else 0.0
        surplus = edge_surplus_lb_undirected(sub)
        loc = sum(count_loc(sub.nodes[u].get("abs_path", abs_by_id.get(u, ""))) for u in sub.nodes())

        cycle_pressure_lb += surplus
        totals_nodes += n
        totals_edges += m
        totals_loc += loc

        # cycles
        candidates = enumerate_cycles_filtered(sub, max_size=args.max_cycle_size)
        reps = greedy_edge_disjoint_two_pass(
            candidates,
            per_size_cap=args.per_size_cap,
            max_total=args.max_cycles_per_scc,
        )

        rep_cycles: List[Dict] = []
        for j, cyc in enumerate(reps):
            rep_cycles.append(
                {
                    "id": f"scc_{idx}_cycle_{j}",
                    "length": len(cyc),
                    "nodes": cyc,
                    "edges": cycle_edge_objects(cyc, relation),
                }
            )

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
                "representative_cycles": rep_cycles,
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
            "max_cycle_size": args.max_cycle_size,
            "per_size_cap": args.per_size_cap,
            "max_cycles_per_scc": args.max_cycles_per_scc,
        },
        "global_metrics": global_metrics,
        "sccs": report_sccs,
    }

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote SCC report: {out_path}")
    print(f"  sccs={len(report_sccs)} nodes={G.number_of_nodes()} edges={G.number_of_edges()}")


if __name__ == "__main__":
    main()
