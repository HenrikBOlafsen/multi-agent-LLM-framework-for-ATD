#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, collections
import networkx as nx
from typing import List
from pydeps_utils import build_graph_from_pydeps, nontrivial_sccs

# ---- tunables ----
K_CYCLES_PER_SCC = 1
DEDUP_IGNORE_DIRECTION = True

# ---- canonicalization (keeps output deterministic) ----
def canonicalize_cycle(nodes: List[str]):
    if not nodes:
        return tuple()
    cyc = list(nodes)
    n = len(cyc)
    i_min = min(range(n), key=lambda i: cyc[i])
    fwd = tuple(cyc[i_min:] + cyc[:i_min])
    if not DEDUP_IGNORE_DIRECTION:
        return fwd
    rc = list(reversed(cyc))
    j_min = min(range(n), key=lambda i: rc[i])
    rev = tuple(rc[j_min:] + rc[:j_min])
    return fwd if fwd <= rev else rev

# ---- exact SHORTEST directed cycle (fast) ----
def shortest_cycle_one(Gscc: nx.DiGraph) -> List[str]:
    """
    Returns the globally shortest directed simple cycle in Gscc (or [] if none).
    Complexity: O(V * (V+E)) per SCC.
    """
    if Gscc.number_of_edges() == 0:
        return []

    R = Gscc.reverse(copy=False)
    best_len = None
    best_cyc: List[str] | None = None

    for u in Gscc.nodes():
        # BFS on reverse graph from u: shortest x=>u in original
        parent = {u: None}
        dist = {u: 0}
        dq = collections.deque([u])
        while dq:
            x = dq.popleft()
            for y in R.neighbors(x):  # edge y->x in original
                if y not in dist:
                    dist[y] = dist[x] + 1
                    parent[y] = x
                    dq.append(y)

        # close cycles via each out-edge (u->v)
        for v in Gscc.successors(u):
            if v not in dist:
                continue
            # reconstruct shortest path v=>u
            path = [v]
            cur = v
            while cur != u:
                cur = parent[cur]
                path.append(cur)
            cyc = [u] + path
            if cyc and cyc[-1] == u:
                cyc.pop()  # keep ring without duplicate u

            L = len(cyc)
            if best_len is None or L < best_len or (L == best_len and tuple(cyc) < tuple(best_cyc)):
                best_len = L
                best_cyc = cyc

    return best_cyc or []

# ---- your current "top-k by enumeration" logic (unchanged) ----
def extract_representative_cycles(Gscc: nx.DiGraph, k=K_CYCLES_PER_SCC) -> List[List[str]]:
    seen=set(); all_cycles=[]
    for cyc in nx.simple_cycles(Gscc):
        key = canonicalize_cycle(cyc)
        if key and key not in seen:
            seen.add(key); all_cycles.append(list(key))
    if not all_cycles:
        two=[]
        for u,v in Gscc.edges():
            if Gscc.has_edge(v,u):
                key = canonicalize_cycle([u,v])
                if key not in seen:
                    seen.add(key); two.append(list(key))
        two.sort(key=lambda nodes:(len(nodes),tuple(nodes)))
        return two[:max(1,k)] if two else []
    all_cycles.sort(key=lambda nodes:(len(nodes),tuple(nodes)))
    out=[]; cur_len=None
    for cyc in all_cycles:
        L=len(cyc)
        if cur_len is None:
            cur_len=L
        if L==cur_len:
            out.append(cyc)
            if len(out)>=k:
                return out[:k]
        else:
            if len(out)<k:
                cur_len=L; out.append(cyc)
                if len(out)>=k:
                    return out[:k]
            else:
                break
    return out[:max(1,k)]

# ---- JSON shapers (match your example format) ----
def scc_node_objects(nodes: List[str]) -> list[dict]:
    return [{"id": n, "type": "module", "name": n} for n in nodes]

def scc_edge_objects(Gscc: nx.DiGraph) -> list[dict]:
    edges = [{"source": u, "target": v, "relation": "module_dep"} for u, v in Gscc.edges()]
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges

def cycle_edge_objects(cycle_nodes: List[str]) -> list[dict]:
    m=len(cycle_nodes)
    return [{"source": cycle_nodes[i], "target": cycle_nodes[(i+1)%m], "relation": "module_dep"} for i in range(m)]

# ---- CLI ----
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Write representative cycles JSON from pydeps graph.")
    ap.add_argument("pydeps_json", help="pydeps intermediate JSON (deps-output)")
    ap.add_argument("output_json", nargs="?", default="module_cycles.json", help="Output JSON path")
    ap.add_argument("--k", type=int, default=K_CYCLES_PER_SCC, help="Cycles per SCC: 1 = exact shortest (fast), >1 = enumerate")
    args = ap.parse_args()

    repo_root = os.getenv("REPO_ROOT", os.getcwd())
    G = build_graph_from_pydeps(args.pydeps_json, repo_root=repo_root)

    sccs = nontrivial_sccs(G)
    sccs = sorted(sccs, key=len, reverse=True)

    out = {"sccs": []}
    for idx, scc in enumerate(sccs):
        sub = G.subgraph(scc).copy()
        node_list = sorted(scc)
        edges_all = scc_edge_objects(sub)

        rep_cycles = []
        if args.k == 1:
            cyc = shortest_cycle_one(sub)
            if cyc:
                rep_cycles.append({
                    "id": f"scc_{idx}_cycle_0",
                    "length": len(cyc),
                    "nodes": cyc,
                    "edges": cycle_edge_objects(cyc),
                    "summary": f"Shortest cycle of length {len(cyc)}",
                })
        else:
            for j, cyc in enumerate(extract_representative_cycles(sub, k=args.k)):
                rep_cycles.append({
                    "id": f"scc_{idx}_cycle_{j}",
                    "length": len(cyc),
                    "nodes": cyc,
                    "edges": cycle_edge_objects(cyc),
                    "summary": f"Representative cycle of length {len(cyc)}",
                })

        out["sccs"].append({
            "id": f"scc_{idx}",
            "size": sub.number_of_nodes(),
            "edge_count": sub.number_of_edges(),
            "nodes": scc_node_objects(node_list),
            "edges": edges_all,
            "representative_cycles": rep_cycles,
        })

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote representative cycles to: {args.output_json}")
