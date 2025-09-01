# parse_module_cycles.py
import json
import os
import sys
import time
from collections import deque
import networkx as nx

# ======================
# Tunables
# ======================

# Keep up to K cycles per SCC for LLM/refactoring context
K_CYCLES_PER_SCC = 5

# Budgets (tune if needed)
TIME_BUDGET_PER_SCC_SEC = 5.0      # total wall-clock per SCC (Johnson + BFS combined)
MAX_CYCLES_ENUM = 2000             # cap on Johnson enumeration
BFS_MAX_EXPANSIONS = 100_000       # per-edge BFS expansions

# Johnson only on "small" SCCs
MAX_SCC_NODES_FOR_JOHNSON = 200
MAX_SCC_EDGES_FOR_JOHNSON = 2000

# De-dup policy: treat a cycle and its reverse as the same (good for refactoring context)
DEDUP_IGNORE_DIRECTION = True

# Skip modules that look like tests
SKIP_TESTS = True


# ======================
# Helpers
# ======================

def is_test_node(name: str) -> bool:
    if not SKIP_TESTS:
        return False
    lowered = name.lower()
    return "test" in lowered or "tests" in lowered


def _normalize_var_name(raw: str) -> str:
    """
    Depends 'variables' entries can be full paths, sometimes with "(...)" suffixes.
    Normalize to a module key: basename without extension; drop any '(... )' suffix.
    """
    # Drop trailing "(...)" suffix if present
    if "(" in raw and raw.endswith(")"):
        raw = raw.split("(")[-1][:-1]
    base = os.path.basename(raw)
    mod, _ = os.path.splitext(base)
    return mod


def load_module_edges_from_sdsm(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    variables = data.get("variables", [])
    edges = []
    nodes = set()

    for cell in data.get("cells", []):
        src_idx = cell.get("src")
        dst_idx = cell.get("dest")
        if src_idx is None or dst_idx is None:
            continue
        try:
            src_full = variables[src_idx]
            dst_full = variables[dst_idx]
        except (IndexError, TypeError):
            continue

        src_mod = _normalize_var_name(src_full)
        dst_mod = _normalize_var_name(dst_full)

        if is_test_node(src_mod) or is_test_node(dst_mod):
            continue

        if src_mod == "" or dst_mod == "":
            continue

        nodes.add(src_mod)
        nodes.add(dst_mod)
        edges.append((src_mod, dst_mod))

    return nodes, edges


def canonicalize_cycle(cyc):
    """
    Canonicalize a cycle for deduplication:
      - rotate so lexicographically smallest node is first
      - optionally, compare forward vs reversed rotations and pick lexicographically smaller
    Return a tuple.
    """
    if not cyc:
        return tuple()
    n = len(cyc)

    # forward rotation
    fmin = min(range(n), key=lambda i: cyc[i])
    fwd = tuple(cyc[fmin:] + cyc[:fmin])

    if not DEDUP_IGNORE_DIRECTION:
        return fwd

    # reverse rotation
    rc = list(reversed(cyc))
    rmin = min(range(n), key=lambda i: rc[i])
    rev = tuple(rc[rmin:] + rc[:rmin])

    return fwd if fwd <= rev else rev


# ======================
# Cycle finders (budgeted)
# ======================

def shortest_cycle_through_edge_bfs(Gscc: nx.DiGraph, u, v, max_expansions=BFS_MAX_EXPANSIONS):
    """
    Find a shortest directed cycle that includes edge (u->v) by searching
    for a shortest path v -> u (budgeted by expansion count).
    Returns canonicalized node list or None.
    """
    if u not in Gscc or v not in Gscc or not Gscc.has_edge(u, v):
        return None

    q = deque([(v, [v])])
    visited = {v}
    expansions = 0

    while q:
        node, path = q.popleft()
        expansions += 1
        if expansions > max_expansions:
            return None
        for nxt in Gscc.successors(node):
            if nxt == u:
                cyc = [u] + path  # u -> ... -> v -> u
                return list(canonicalize_cycle(cyc))
            if nxt not in visited:
                visited.add(nxt)
                q.append((nxt, path + [nxt]))
    return None


def cycles_via_johnson(Gscc: nx.DiGraph, k: int, time_budget: float, max_enum: int, seen: set):
    """
    Try Johnson's algorithm (nx.simple_cycles) with time and count budgets.
    Append up to k new (deduped) cycles into 'picked'.
    Returns (picked, elapsed_seconds).
    """
    start = time.time()
    picked = []
    count = 0
    try:
        for cyc in nx.simple_cycles(Gscc):
            count += 1
            if count > max_enum or (time.time() - start) > time_budget:
                break
            key = canonicalize_cycle(cyc)
            if key in seen:
                continue
            seen.add(key)
            picked.append(list(key))
            if len(picked) >= k:
                break
    except Exception:
        # Large SCCs can make Johnson heavy; ignore and fall back
        pass
    return picked, time.time() - start


def cycles_via_bfs_edges(Gscc: nx.DiGraph, k: int, time_budget: float, seen: set):
    """
    Edge-scanning BFS fallback: for each edge (u->v), try to form a shortest cycle
    that includes that edge, within the remaining time budget. Dedups via 'seen'.
    """
    start = time.time()
    picked = []
    for (u, v) in Gscc.edges():
        if (time.time() - start) > time_budget:
            break
        cyc = shortest_cycle_through_edge_bfs(Gscc, u, v)
        if not cyc:
            continue
        key = canonicalize_cycle(cyc)
        if key in seen:
            continue
        seen.add(key)
        picked.append(list(key))
        if len(picked) >= k:
            break
    return picked


def any_directed_cycle_nodes(Gscc: nx.DiGraph, seen: set):
    """
    Final fallback: return *some* directed cycle (not necessarily shortest).
    Uses networkx.find_cycle; guaranteed to find one in a cyclic SCC.
    Returns canonicalized node list or None if somehow not found.
    """
    try:
        cyc_edges = nx.find_cycle(Gscc, orientation='original')
        # cyc_edges is a list of (u, v, direction). Reconstruct node order.
        nodes = []
        for i, (u, v, _dir) in enumerate(cyc_edges):
            if i == 0:
                nodes.append(u)
            nodes.append(v)
        if nodes and nodes[0] == nodes[-1]:
            nodes = nodes[:-1]
        key = canonicalize_cycle(nodes)
        if key in seen:
            return None
        seen.add(key)
        return list(key)
    except nx.NetworkXNoCycle:
        return None


# ======================
# Orchestration
# ======================

def extract_representative_cycles(Gscc: nx.DiGraph, k=K_CYCLES_PER_SCC, time_budget=TIME_BUDGET_PER_SCC_SEC):
    """
    For each SCC:
      1) If SCC is small, try Johnson with a partial, budgeted scan (good at short cycles).
      2) Top up via BFS-over-edges within the remaining time.
      3) If still empty or budgets exhausted, return at least ONE cycle via find_cycle().
    Returns up to k cycles (deduped, canonicalized). Prefers shorter cycles overall.
    """
    n, m = Gscc.number_of_nodes(), Gscc.number_of_edges()
    remaining = float(time_budget)
    seen = set()
    collected = []

    # Johnson on small SCCs
    if n <= MAX_SCC_NODES_FOR_JOHNSON and m <= MAX_SCC_EDGES_FOR_JOHNSON and remaining > 0.0:
        got, elapsed = cycles_via_johnson(Gscc, k, remaining, MAX_CYCLES_ENUM, seen)
        collected.extend(got)
        remaining = max(0.0, remaining - elapsed)

    # BFS fallback (or top-up)
    if len(collected) < k and remaining > 0.0:
        topup = cycles_via_bfs_edges(Gscc, k - len(collected), remaining, seen)
        collected.extend(topup)

    # Final safety net: ensure at least one cycle
    if not collected:
        any_cyc = any_directed_cycle_nodes(Gscc, seen)
        if any_cyc:
            collected.append(any_cyc)

    # Prefer shorter cycles (and deterministic order)
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


def run_pipeline(sdsm_path: str, output_path: str):
    nodes, edges = load_module_edges_from_sdsm(sdsm_path)
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    G.add_edges_from(edges)
    print(f"Module graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Nontrivial SCCs = architectural smell instances
    sccs = [s for s in nx.strongly_connected_components(G) if len(s) > 1]
    sccs = sorted(sccs, key=len, reverse=True)
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


# ======================
# CLI
# ======================

if __name__ == "__main__":
    if not (2 <= len(sys.argv) <= 3):
        print("Usage: python parse_module_cycles.py <sdsm.json> [output.json]")
        sys.exit(1)
    sdsm = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else "module_cycles.json"
    run_pipeline(sdsm, out)
