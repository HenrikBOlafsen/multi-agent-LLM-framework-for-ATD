# ===== Tunables =====
K_CYCLES_PER_SCC = 5
DEDUP_IGNORE_DIRECTION = True

import argparse, json, os
import networkx as nx
from typing import List, Set

# Reuse shared helpers so edge-kind filtering and paths match other steps
from sdsm_utils import (
    build_graph_from_sdsm,
    nontrivial_sccs,
    parse_edge_kinds_from_env,
)

# ---------- Cycle utilities ----------
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

def extract_representative_cycles(Gscc: nx.DiGraph, k=K_CYCLES_PER_SCC, time_budget=None) -> List[List[str]]:
    """
    Enumerate all simple cycles using Johnson's algorithm (networkx.simple_cycles),
    then return up to k shortest canonicalized cycles (≥1 if any exists).
    """
    seen = set()
    all_cycles: List[List[str]] = []
    for cyc in nx.simple_cycles(Gscc):
        key = canonicalize_cycle(cyc)
        if key and key not in seen:
            seen.add(key)
            all_cycles.append(list(key))

    # Fallback to 2-cycles if Johnson somehow yields none
    if not all_cycles:
        two_cycles = []
        for u, v in Gscc.edges():
            if Gscc.has_edge(v, u):
                key = canonicalize_cycle([u, v])
                if key not in seen:
                    seen.add(key)
                    two_cycles.append(list(key))
        two_cycles.sort(key=lambda nodes: (len(nodes), tuple(nodes)))
        return two_cycles[:max(1, k)] if two_cycles else []

    all_cycles.sort(key=lambda nodes: (len(nodes), tuple(nodes)))

    out = []
    cur_len = None
    for cyc in all_cycles:
        L = len(cyc)
        if cur_len is None:
            cur_len = L
        if L == cur_len:
            out.append(cyc)
            if len(out) >= k:
                return out[:k]
        else:
            if len(out) < k:
                cur_len = L
                out.append(cyc)
                if len(out) >= k:
                    return out[:k]
            else:
                break
    return out[:max(1, k)]

# ---------- JSON helpers to keep the OLD format ----------
def scc_node_objects(nodes: List[str]) -> List[dict]:
    # Keep your original per-node objects: id/type/name
    # (old files show type="module" and name equal to id) :contentReference[oaicite:1]{index=1}
    return [{"id": n, "type": "module", "name": n} for n in nodes]

def scc_edge_objects(Gscc: nx.DiGraph) -> List[dict]:
    # Old format includes every SCC edge with relation="module_dep" :contentReference[oaicite:2]{index=2}
    edges = [{"source": u, "target": v, "relation": "module_dep"} for u, v in Gscc.edges()]
    # Make deterministic
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges

def cycle_edge_objects(cycle_nodes: List[str]) -> List[dict]:
    # Build the directed ring; relation kept as "module_dep" like before :contentReference[oaicite:3]{index=3}
    m = len(cycle_nodes)
    edges = []
    for i in range(m):
        u = cycle_nodes[i]
        v = cycle_nodes[(i + 1) % m]
        edges.append({"source": u, "target": v, "relation": "module_dep"})
    return edges

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(description="Parse module-level SCCs and write representative cycles JSON (old format).")
    ap.add_argument("sdsm_json", help="Depends SDSM JSON (module-level)")
    ap.add_argument("output_json", nargs="?", default="module_cycles.json", help="Output JSON path (old format)")
    ap.add_argument("--k", type=int, default=K_CYCLES_PER_SCC, help="Max representative cycles per SCC")
    args = ap.parse_args()

    kinds: Set[str] = parse_edge_kinds_from_env(default_csv=os.getenv("EDGE_KINDS", "Import,Include,Extend,Implement,Mixin"))

    G = build_graph_from_sdsm(args.sdsm_json, edge_kinds=kinds)  # consistent with metrics step :contentReference[oaicite:4]{index=4}
    sccs = nontrivial_sccs(G)  # size>1, largest first for determinism :contentReference[oaicite:5]{index=5}

    out = {"sccs": []}

    for idx, scc in enumerate(sccs):
        sub = G.subgraph(scc).copy()
        # Deterministic order for nodes in the JSON
        node_list = sorted(scc)
        edges_all = scc_edge_objects(sub)

        # improved selection of shortest cycles (≤5 but ≥1 if any) using Johnson
        rep_cycles = []
        for j, cyc in enumerate(extract_representative_cycles(sub, k=args.k)):
            rep_cycles.append({
                "id": f"scc_{idx}_cycle_{j}",
                "length": len(cyc),
                "nodes": cyc,                         # list of strings, like before
                "edges": cycle_edge_objects(cyc),     # ring edges with relation="module_dep"
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

if __name__ == "__main__":
    main()
