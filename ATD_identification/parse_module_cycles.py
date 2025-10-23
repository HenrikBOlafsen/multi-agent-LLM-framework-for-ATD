#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from collections import deque
from typing import List, Optional, Iterable, Set, Dict
import networkx as nx
from pydeps_utils import build_graph_from_pydeps

# ---- tunables ----
# Greedy, edge-disjoint, largest-first cycles per SCC, capped by MAX_CYCLE_SIZE.
# Selection is TWO-PASS:
#   Pass 1: up to PER_SIZE_CAP cycles for each size (longest -> shortest)
#   Pass 2: top up with remaining edge-disjoint cycles (largest-first)
# K_CYCLES_PER_SCC is an overall cap across both passes (0 = no overall cap).
K_CYCLES_PER_SCC = 0
MAX_CYCLE_SIZE = 8   # default upper bound on cycle length to consider
PER_SIZE_CAP = 2     # default: pick up to 2 cycles of each size in pass 1

# (canonicalization only used during enumeration)
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

def _enumerate_cycles_filtered(
    Gscc: nx.DiGraph,
    *,
    max_size: Optional[int] = None,
) -> list[list[str]]:
    """Enumerate all simple cycles (≤ max_size) sorted largest-first deterministically."""
    seen = set()
    cycles: list[list[str]] = []
    for cyc in nx.simple_cycles(Gscc):
        key = _canonicalize_cycle(cyc)
        if not key or key in seen:
            continue
        if max_size is not None and len(key) > max_size:
            continue
        seen.add(key)
        cycles.append(list(key))

    if not cycles:
        # Fallback: include any 2-cycles (u<->v) if present and within max_size
        two = []
        for u, v in Gscc.edges():
            if Gscc.has_edge(v, u):
                key = _canonicalize_cycle([u, v])
                if key not in seen and (max_size is None or len(key) <= max_size):
                    seen.add(key)
                    two.append(list(key))
        cycles = two

    # Largest length first; tie-break lexicographically for determinism
    cycles.sort(key=lambda nodes: (len(nodes), tuple(nodes)), reverse=True)
    return cycles


def _scc_node_objects(nodes: list[str]) -> list[dict]:
    return [{"id": n, "type": "module", "name": n} for n in nodes]


def _scc_edge_objects(Gscc: nx.DiGraph) -> list[dict]:
    edges = [{"source": u, "target": v, "relation": "module_dep"} for u, v in Gscc.edges()]
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges


def _cycle_edge_objects(nodes: list[str]) -> list[dict]:
    m = len(nodes)
    return [
        {"source": nodes[i], "target": nodes[(i + 1) % m], "relation": "module_dep"}
        for i in range(m)
    ]


def _edges_of_cycle(nodes: list[str]) -> list[tuple[str, str]]:
    """Return directed edges (u,v) that form this cycle in order."""
    m = len(nodes)
    return [(nodes[i], nodes[(i + 1) % m]) for i in range(m)]


def _greedy_edge_disjoint(
    candidates: Iterable[list[str]],
    *,
    max_pick: int = 0,  # 0 means "no explicit cap"
) -> list[list[str]]:
    """Greedily pick EDGE-disjoint cycles, largest-first (candidates must already be sorted)."""
    picked: list[list[str]] = []
    used_edges: Set[tuple[str, str]] = set()
    for cyc in candidates:
        cedges = set(_edges_of_cycle(cyc))
        if cedges.isdisjoint(used_edges):
            picked.append(cyc)
            used_edges.update(cedges)
            if max_pick > 0 and len(picked) >= max_pick:
                break
    return picked


def _greedy_edge_disjoint_two_pass(
    candidates: list[list[str]],
    *,
    per_size_cap: int = 2,
    max_total: int = 0,   # 0 = no overall cap
) -> list[list[str]]:
    """
    Pass 1: pick up to `per_size_cap` edge-disjoint cycles for each length (largest->smallest).
    Pass 2: continue picking remaining edge-disjoint cycles (largest-first) with no per-size cap.
    `candidates` must already be sorted largest-first deterministically.
    """
    if per_size_cap <= 0:
        # No per-size balancing requested: just do the original behavior
        return _greedy_edge_disjoint(candidates, max_pick=max_total)

    # ----- Pass 1: per-size cap -----
    picked: list[list[str]] = []
    used_edges: Set[tuple[str, str]] = set()
    picked_keys: Set[tuple[str, ...]] = set()

    by_len: Dict[int, list[list[str]]] = {}
    for cyc in candidates:
        by_len.setdefault(len(cyc), []).append(cyc)

    for L in sorted(by_len.keys(), reverse=True):
        taken = 0
        for cyc in by_len[L]:
            cedges = set(_edges_of_cycle(cyc))
            if cedges.isdisjoint(used_edges):
                picked.append(cyc)
                used_edges.update(cedges)
                picked_keys.add(tuple(cyc))
                taken += 1
                if max_total > 0 and len(picked) >= max_total:
                    return picked
                if taken >= per_size_cap:
                    break  # move to next size

    # ----- Pass 2: largest-first top-up (no per-size cap) -----
    for cyc in candidates:
        if tuple(cyc) in picked_keys:
            continue
        cedges = set(_edges_of_cycle(cyc))
        if cedges.isdisjoint(used_edges):
            picked.append(cyc)
            used_edges.update(cedges)
            if max_total > 0 and len(picked) >= max_total:
                break

    return picked


# ---- CLI ----
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Write representative edge-disjoint largest cycles JSON from pydeps graph (two-pass selection).")
    ap.add_argument("pydeps_json", help="pydeps intermediate JSON (deps-output)")
    ap.add_argument("output_json", nargs="?", default="module_cycles.json", help="Output JSON path")
    ap.add_argument(
        "--k",
        type=int,
        default=K_CYCLES_PER_SCC,
        help="Max total representative cycles per SCC across both passes (0 = no overall cap).",
    )
    ap.add_argument(
        "--max-size",
        type=int,
        default=MAX_CYCLE_SIZE,
        help=f"Maximum cycle length to consider (default {MAX_CYCLE_SIZE}).",
    )
    ap.add_argument(
        "--per-size",
        type=int,
        default=PER_SIZE_CAP,
        help="Pick up to N cycles for each cycle length in pass 1 (default 2). Use 0 to disable per-size balancing.",
    )
    args = ap.parse_args()

    repo_root = os.getenv("REPO_ROOT", os.getcwd())
    G = build_graph_from_pydeps(args.pydeps_json, repo_root=repo_root)

    # Nontrivial SCCs, largest first
    sccs = [s for s in nx.strongly_connected_components(G) if len(s) > 1]
    sccs.sort(key=len, reverse=True)

    out = {"sccs": []}
    for idx, scc in enumerate(sccs):
        sub = G.subgraph(scc)
        node_list = sorted(scc)
        edges_all = _scc_edge_objects(sub)

        # 1) enumerate all cycles (≤ max-size), sorted largest-first
        candidates = _enumerate_cycles_filtered(sub, max_size=args.max_size)

        # 2) two-pass selection: (a) per-size cap, then (b) largest-first top-up
        rep_nodes_list = _greedy_edge_disjoint_two_pass(
            candidates,
            per_size_cap=args.per_size,
            max_total=args.k,
        )

        # 3) shape JSON (no summary field)
        rep_cycles: list[dict] = []
        for j, cyc in enumerate(rep_nodes_list):
            rep_cycles.append({
                "id": f"scc_{idx}_cycle_{j}",
                "length": len(cyc),
                "nodes": cyc,
                "edges": _cycle_edge_objects(cyc),
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
