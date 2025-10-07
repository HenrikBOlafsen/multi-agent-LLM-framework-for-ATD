#!/usr/bin/env python3
from __future__ import annotations
import os, json, time, argparse
from collections import deque
import networkx as nx

from sdsm_utils import (
    build_graph_from_sdsm,
    nontrivial_sccs,
    parse_edge_kinds_from_env,  # new helper
)

# ===== Tunables for representative cycles =====
K_CYCLES_PER_SCC = 5
TIME_BUDGET_PER_SCC_SEC = 5.0
MAX_CYCLES_ENUM = 2000
BFS_MAX_EXPANSIONS = 100_000
MAX_SCC_NODES_FOR_JOHNSON = 200
MAX_SCC_EDGES_FOR_JOHNSON = 2000
DEDUP_IGNORE_DIRECTION = True  # treat reversed cycles as duplicates


def canonicalize_cycle(cyc):
    if not cyc:
        return tuple()
    n = len(cyc)
    fmin = min(range(n), key=lambda i: cyc[i])
    fwd = tuple(cyc[fmin:] + cyc[:fmin])
    if not DEDUP_IGNORE_DIRECTION:
        return fwd
    rc = list(reversed(cyc))
    rmin = min(range(n), key=lambda i: rc[i])
    rev = tuple(rc[rmin:] + rc[:rmin])
    return fwd if fwd <= rev else rev


def shortest_cycle_through_edge_bfs(Gscc: nx.DiGraph, u, v, max_expansions=BFS_MAX_EXPANSIONS):
    if u not in Gscc or v not in Gscc or not Gscc.has_edge(u, v):
        return None
    q = deque([(v, [v])]); visited = {v}; expansions = 0
    while q:
        node, path = q.popleft()
        expansions += 1
        if expansions > max_expansions:
            return None
        for nxt in Gscc.successors(node):
            if nxt == u:
                cyc = [u] + path
                return list(canonicalize_cycle(cyc))
            if nxt not in visited:
                visited.add(nxt)
                q.append((nxt, path + [nxt]))
    return None


def cycles_via_johnson(Gscc, k, time_budget, max_enum, seen):
    start = time.time(); picked, count = [], 0
    try:
        for cyc in nx.simple_cycles(Gscc):
            count += 1
            if count > max_enum or (time.time() - start) > time_budget:
                break
            key = canonicalize_cycle(cyc)
            if key in seen:
                continue
            seen.add(key); picked.append(list(key))
            if len(picked) >= k:
                break
    except Exception:
        pass
    return picked, time.time() - start


def cycles_via_bfs_edges(Gscc, k, time_budget, seen):
    start = time.time(); picked = []
    for (u, v) in Gscc.edges():
        if (time.time() - start) > time_budget:
            break
        cyc = shortest_cycle_through_edge_bfs(Gscc, u, v)
        if not cyc:
            continue
        key = canonicalize_cycle(cyc)
        if key in seen:
            continue
        seen.add(key); picked.append(list(key))
        if len(picked) >= k:
            break
    return picked


def any_directed_cycle_nodes(Gscc, seen):
    try:
        cyc_edges = nx.find_cycle(Gscc, orientation='original')
        nodes = []
        for i, (u, v, _dir) in enumerate(cyc_edges):
            if i == 0: nodes.append(u)
            nodes.append(v)
        if nodes and nodes[0] == nodes[-1]:
            nodes = nodes[:-1]
        key = canonicalize_cycle(nodes)
        if key in seen:
            return None
        seen.add(key); return list(key)
    except nx.NetworkXNoCycle:
        return None


def extract_representative_cycles(Gscc: nx.DiGraph, k=K_CYCLES_PER_SCC, time_budget=TIME_BUDGET_PER_SCC_SEC):
    n, m = Gscc.number_of_nodes(), Gscc.number_of_edges()
    remaining = float(time_budget)
    seen = set(); collected = []

    if n <= MAX_SCC_NODES_FOR_JOHNSON and m <= MAX_SCC_EDGES_FOR_JOHNSON and remaining > 0.0:
        got, elapsed = cycles_via_johnson(Gscc, k, remaining, MAX_CYCLES_ENUM, seen)
        collected.extend(got); remaining = max(0.0, remaining - elapsed)

    if len(collected) < k and remaining > 0.0:
        topup = cycles_via_bfs_edges(Gscc, k - len(collected), remaining, seen)
        collected.extend(topup)

    if not collected:
        any_cyc = any_directed_cycle_nodes(Gscc, seen)
        if any_cyc:
            collected.append(any_cyc)

    collected.sort(key=lambda c: (len(c), tuple(c)))
    return collected[:k]


def build_output(G: nx.DiGraph, sccs_with_cycles):
    out = {"sccs": []}
    for idx, (scc_nodes, cycles) in enumerate(sccs_with_cycles):
        sub = G.subgraph(scc_nodes).copy()
        nodes = [{"id": n, "type": "module", "name": n} for n in sorted(sub.nodes())]
        edges = [{"source": u, "target": v, "relation": "module_dep"} for u, v in sub.edges()]
        out["sccs"].append({
            "id": f"scc_{idx}",
            "size": sub.number_of_nodes(),
            "edge_count": sub.number_of_edges(),
            "nodes": nodes,
            "edges": edges,
            "representative_cycles": [
                {
                    "id": f"scc_{idx}_cycle_{j}",
                    "length": len(cyc),
                    "nodes": cyc,
                    "edges": [
                        {"source": cyc[t], "target": cyc[(t + 1) % len(cyc)], "relation": "module_dep"}
                        for t in range(len(cyc))
                    ],
                    "summary": f"Representative cycle of length {len(cyc)}"
                }
                for j, cyc in enumerate(cycles)
            ]
        })
    return out


def run_pipeline(sdsm_path: str, output_path: str, edge_kinds: set[str]):
    G = build_graph_from_sdsm(sdsm_path, edge_kinds=edge_kinds)
    print(f"Module graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    sccs = nontrivial_sccs(G)
    print(f"Found {len(sccs)} cyclic SCC(s).")

    sccs_with_cycles = []
    for scc in sccs:
        sub = G.subgraph(scc).copy()
        rep_cycles = extract_representative_cycles(sub, k=K_CYCLES_PER_SCC, time_budget=TIME_BUDGET_PER_SCC_SEC)
        sccs_with_cycles.append((scc, rep_cycles))

    result = build_output(G, sccs_with_cycles)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Module-level SCCs & representative cycles written to: {output_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Parse module-level SCCs & representative cycles from Depends SDSM.")
    ap.add_argument("sdsm_json", help="Depends SDSM JSON (module-level)")
    ap.add_argument("output_json", nargs="?", default="module_cycles.json", help="Output JSON path")
    args = ap.parse_args()

    kinds = parse_edge_kinds_from_env(default_csv=os.getenv("EDGE_KINDS", "Import,Include,Extend,Implement,Mixin"))
    run_pipeline(args.sdsm_json, args.output_json, edge_kinds=kinds)
