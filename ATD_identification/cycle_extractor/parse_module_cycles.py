#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from collections import deque
from typing import List
import networkx as nx
from pydeps_utils import build_graph_from_pydeps

# ---- tunables ----
K_CYCLES_PER_SCC = 1  # 1 = fast exact shortest cycle; >1 = enumerate
# (canonicalization only used when k>1)
def _canonicalize_cycle(nodes: List[str]) -> tuple[str, ...]:
    if not nodes:
        return ()
    cyc = list(nodes)
    i = min(range(len(cyc)), key=lambda j: cyc[j])
    fwd = tuple(cyc[i:] + cyc[:i])
    rc = list(reversed(cyc))
    j = min(range(len(rc)), key=lambda t: rc[t])
    rev = tuple(rc[j:] + rc[:j])
    return fwd if fwd <= rev else rev

def _shortest_cycle_one(Gscc: nx.DiGraph) -> List[str]:
    """
    Globally shortest directed simple cycle (directed girth) via reverse-BFS.
    O(V * (V+E)) per SCC. Returns [] if none.
    """
    if Gscc.number_of_edges() == 0:
        return []
    R = Gscc.reverse(copy=False)
    best_len = None
    best_cyc: List[str] | None = None
    for u in Gscc.nodes():
        parent = {u: None}
        dist = {u: 0}
        q = deque([u])
        while q:
            x = q.popleft()
            for y in R.neighbors(x):  # y->x in original
                if y not in dist:
                    dist[y] = dist[x] + 1
                    parent[y] = x
                    q.append(y)
        for v in Gscc.successors(u):
            if v not in dist:
                continue
            path = [v]
            cur = v
            while cur != u:
                cur = parent[cur]
                path.append(cur)
            cyc = [u] + path
            if cyc and cyc[-1] == u:
                cyc.pop()
            L = len(cyc)
            if best_len is None or L < best_len or (L == best_len and tuple(cyc) < tuple(best_cyc)):
                best_len = L
                best_cyc = cyc
    return best_cyc or []

def _topk_cycles_by_enumeration(Gscc: nx.DiGraph, k: int) -> list[list[str]]:
    # Johnson via networkx; dedup + deterministic shortest-first selection.
    seen = set()
    all_cycles: list[list[str]] = []
    for cyc in nx.simple_cycles(Gscc):
        key = _canonicalize_cycle(cyc)
        if key and key not in seen:
            seen.add(key)
            all_cycles.append(list(key))
    if not all_cycles:
        # Fallback: include any 2-cycles if present
        two = []
        for u, v in Gscc.edges():
            if Gscc.has_edge(v, u):
                key = _canonicalize_cycle([u, v])
                if key not in seen:
                    seen.add(key)
                    two.append(list(key))
        two.sort(key=lambda nodes: (len(nodes), tuple(nodes)))
        return two[:max(1, k)] if two else []
    all_cycles.sort(key=lambda nodes: (len(nodes), tuple(nodes)))
    out, cur_len = [], None
    for cyc in all_cycles:
        L = len(cyc)
        if cur_len is None:
            cur_len = L
        if L == cur_len:
            out.append(cyc)
            if len(out) >= k:
                break
        else:
            if len(out) < k:
                cur_len = L
                out.append(cyc)
                if len(out) >= k:
                    break
            else:
                break
    return out[:max(1, k)]

# ---- JSON shapers (match your example format) ----
def _scc_node_objects(nodes: list[str]) -> list[dict]:
    return [{"id": n, "type": "module", "name": n} for n in nodes]

def _scc_edge_objects(Gscc: nx.DiGraph) -> list[dict]:
    edges = [{"source": u, "target": v, "relation": "module_dep"} for u, v in Gscc.edges()]
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges

def _cycle_edge_objects(nodes: list[str]) -> list[dict]:
    m = len(nodes)
    return [{"source": nodes[i], "target": nodes[(i + 1) % m], "relation": "module_dep"} for i in range(m)]

# ---- CLI ----
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Write representative cycles JSON from pydeps graph.")
    ap.add_argument("pydeps_json", help="pydeps intermediate JSON (deps-output)")
    ap.add_argument("output_json", nargs="?", default="module_cycles.json", help="Output JSON path")
    ap.add_argument("--k", type=int, default=K_CYCLES_PER_SCC,
                    help="1 = exact shortest cycle (fast). >1 = enumerate and pick up to k shortest.")
    args = ap.parse_args()

    repo_root = os.getenv("REPO_ROOT", os.getcwd())
    G = build_graph_from_pydeps(args.pydeps_json, repo_root=repo_root)

    # Nontrivial SCCs, largest first
    sccs = [s for s in nx.strongly_connected_components(G) if len(s) > 1]
    sccs.sort(key=len, reverse=True)

    out = {"sccs": []}
    for idx, scc in enumerate(sccs):
        sub = G.subgraph(scc)  # view is fine
        node_list = sorted(scc)
        edges_all = _scc_edge_objects(sub)

        rep_cycles: list[dict] = []
        if args.k == 1:
            cyc = _shortest_cycle_one(sub)
            if cyc:
                rep_cycles.append({
                    "id": f"scc_{idx}_cycle_0",
                    "length": len(cyc),
                    "nodes": cyc,
                    "edges": _cycle_edge_objects(cyc),
                    "summary": f"Shortest cycle of length {len(cyc)}",
                })
        else:
            for j, cyc in enumerate(_topk_cycles_by_enumeration(sub, k=args.k)):
                rep_cycles.append({
                    "id": f"scc_{idx}_cycle_{j}",
                    "length": len(cyc),
                    "nodes": cyc,
                    "edges": _cycle_edge_objects(cyc),
                    "summary": f"Representative cycle of length {len(cyc)}",
                })

        out["sccs"].append({
            "id": f"scc_{idx}",
            "size": sub.number_of_nodes(),
            "edge_count": sub.number_of_edges(),
            "nodes": _scc_node_objects(node_list),
            "edges": edges_all,
            "representative_cycles": rep_cycles,
        })

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote representative cycles to: {args.output_json}")
