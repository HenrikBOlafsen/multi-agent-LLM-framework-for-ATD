"""Shared helpers for loading Depends SDSM and building graphs/metrics (language-agnostic)."""
from __future__ import annotations

import json, os
from typing import Iterable, Tuple, Set, Dict, List
import networkx as nx

def parse_edge_kinds_from_env(default_csv: str) -> Set[str]:
    """EDGE_KINDS comes from environment (set by analyze_cycles.sh)."""
    csv = os.getenv("EDGE_KINDS", default_csv) or ""
    return {k.strip() for k in csv.split(",") if k.strip()}

# ----- Paths -----
def detect_repo_root(paths: Iterable[str]) -> str:
    env_root = os.getenv("REPO_ROOT")
    if env_root:
        return os.path.realpath(env_root)
    abss = [os.path.realpath(p) for p in paths if isinstance(p, str)]
    try:
        return os.path.commonpath(abss) if abss else os.getcwd()
    except ValueError:
        return os.getcwd()

def repo_relative_key(abs_path: str, repo_root: str) -> str:
    """Repo-relative POSIX-ish key; keep original filename + extension."""
    ap = os.path.realpath(abs_path)
    rr = os.path.realpath(repo_root)
    return os.path.relpath(ap, rr).replace("\\", "/")

def key_to_abs_path(key: str, repo_root: str) -> str:
    return os.path.realpath(os.path.join(repo_root, key))

def count_loc(abs_path: str) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except (FileNotFoundError, IsADirectoryError):
        return 0

# ----- SDSM -> graph -----
def load_edges_from_sdsm(path: str, edge_kinds: Set[str]) -> Tuple[Set[str], Set[Tuple[str, str]], str]:
    """Parse Depends SDSM (file granularity) into (nodes, edges, repo_root)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    variables = data.get("variables", [])
    repo_root = detect_repo_root(v for v in variables if isinstance(v, str))

    key_from_idx: Dict[int, str] = {}
    for i, raw in enumerate(variables):
        if isinstance(raw, str):
            key_from_idx[i] = repo_relative_key(raw, repo_root)

    nodes: Set[str] = set()
    edges: Set[Tuple[str, str]] = set()

    for cell in data.get("cells", []):
        src_idx = cell.get("src")
        dst_idx = cell.get("dest")
        if src_idx is None or dst_idx is None:
            continue
        vals: Dict[str, float] = cell.get("values", {}) or {}
        # keep only selected relation kinds (non-zero weight)
        if not any(k in edge_kinds and vals.get(k, 0) for k in vals):
            continue

        src = key_from_idx.get(src_idx, "")
        dst = key_from_idx.get(dst_idx, "")
        if not src or not dst or src == dst:
            continue

        edges.add((src, dst))
        nodes.add(src); nodes.add(dst)

    return nodes, edges, repo_root

def build_graph_from_sdsm(path: str, edge_kinds: Set[str]) -> nx.DiGraph:
    nodes, edges, repo_root = load_edges_from_sdsm(path, edge_kinds=edge_kinds)
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    G.add_edges_from(edges)
    G.graph["repo_root"] = repo_root

    for n in G.nodes:
        ap = key_to_abs_path(n, repo_root)
        G.nodes[n]["abs_path"] = ap
        G.nodes[n]["loc"] = count_loc(ap)
    return G

def nontrivial_sccs(G: nx.DiGraph) -> List[set]:
    sccs = [set(s) for s in nx.strongly_connected_components(G) if len(s) > 1]
    return sorted(sccs, key=len, reverse=True)

def scc_metrics(G: nx.DiGraph) -> dict:
    sccs = nontrivial_sccs(G)
    metrics = {
        "scc_count": len(sccs),
        "total_nodes_in_cyclic_sccs": 0,
        "total_edges_in_cyclic_sccs": 0,
        "total_loc_in_cyclic_sccs": 0,
        "max_scc_size": 0,
        "avg_scc_size": 0.0,
        "sccs": [],
    }

    if not sccs:
        metrics["cycle_pressure_lb"] = 0
        return metrics

    sizes: List[int] = []
    for scc in sccs:
        sub = G.subgraph(scc).copy()
        n = sub.number_of_nodes()
        m = sub.number_of_edges()
        sizes.append(n)
        dens = m / (n * (n - 1)) if n > 1 else 0.0
        und = sub.to_undirected()
        m_und = und.number_of_edges()
        edge_surplus_lb = max(0, m_und - (n - 1))
        total_loc = sum(int(G.nodes[u].get("loc", 0)) for u in scc)
        metrics["sccs"].append(
            {
                "size": n,
                "edge_count": m,
                "density_directed": round(dens, 4),
                "edge_surplus_lb": edge_surplus_lb,
                "total_loc": total_loc,
                "avg_loc_per_node": round(total_loc / n, 1),
            }
        )
        metrics["total_nodes_in_cyclic_sccs"] += n
        metrics["total_edges_in_cyclic_sccs"] += m
        metrics["total_loc_in_cyclic_sccs"] += total_loc

    metrics["max_scc_size"] = max(sizes)
    metrics["avg_scc_size"] = round(sum(sizes) / len(sizes), 2)
    metrics["cycle_pressure_lb"] = sum(s["edge_surplus_lb"] for s in metrics["sccs"])
    return metrics
