#!/usr/bin/env python3
"""Shared helpers for loading Depends SDSM and building graphs/metrics."""
from __future__ import annotations

import json
import os
from typing import Iterable, Tuple, Set, Dict, List
import networkx as nx

# ----- Edge-kind profiles (documented & stable) -----
PROFILES: Dict[str, Set[str]] = {
    # import-level coupling (what your refactors actually change)
    "import": {"Import", "Include"},
    # structural: import + inheritance/interface/mixin
    "structural": {"Import", "Include", "Extend", "Implement", "Mixin"},
    # broadest (noisiest) view
    "all": {
        "Import", "Include", "Extend", "Implement", "Mixin",
        "Call", "Cast", "Contain", "Create", "Parameter", "Return",
        "Throw", "Use", "ImplLink",
    },
}


def parse_edge_kinds(profile: str | None, kinds_csv: str | None) -> Set[str]:
    """Pick a set of edge kinds from a profile, optionally overridden by CSV."""
    if kinds_csv and kinds_csv.strip():
        return {k.strip() for k in kinds_csv.split(",") if k.strip()}
    prof = (profile or "import").lower()
    if prof not in PROFILES:
        raise SystemExit(f"--edge-profile must be one of {sorted(PROFILES)}")
    return PROFILES[prof]


# ----- Paths & filtering -----
def is_test_path(rel_path: str, skip_tests: bool) -> bool:
    """Heuristic: ignore test modules if skip_tests=True."""
    if not skip_tests:
        return False
    parts = rel_path.replace("\\", "/").split("/")
    fname = parts[-1]
    if any(p in {"test", "tests"} for p in parts):
        return True
    return fname.startswith("test_") or fname.endswith("_test.py")


def detect_repo_root(paths: Iterable[str]) -> str:
    """Common root for absolute paths; respects REPO_ROOT if set."""
    env_root = os.getenv("REPO_ROOT")
    if env_root:
        return os.path.realpath(env_root)
    abss = [os.path.realpath(p) for p in paths if isinstance(p, str)]
    try:
        return os.path.commonpath(abss) if abss else os.getcwd()
    except ValueError:
        return os.getcwd()


def repo_relative_key(abs_path: str, repo_root: str) -> str:
    """Repo-relative POSIX-ish key without .py; keep '__init__' unfused."""
    ap = os.path.realpath(abs_path)
    rr = os.path.realpath(repo_root)
    rel = os.path.relpath(ap, rr).replace("\\", "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    return rel


# ----- SDSM -> graph -----
def load_edges_from_sdsm(
    path: str, include_tests: bool, edge_kinds: Set[str]
) -> Tuple[Set[str], Set[Tuple[str, str]]]:
    """Parse Depends SDSM (file granularity) into (nodes, edges)."""
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
    skip_tests = not include_tests

    for cell in data.get("cells", []):
        src_idx = cell.get("src")
        dst_idx = cell.get("dest")
        if src_idx is None or dst_idx is None:
            continue
        vals: Dict[str, float] = cell.get("values", {}) or {}
        # filter by selected relation kinds
        if not any(k in edge_kinds and vals.get(k, 0) for k in vals):
            continue

        src = key_from_idx.get(src_idx, "")
        dst = key_from_idx.get(dst_idx, "")
        if not src or not dst or src == dst:
            continue
        if is_test_path(src, skip_tests) or is_test_path(dst, skip_tests):
            continue

        # Keep SDSM direction (observed: for "Import", __init__ -> gui if __init__ imports gui)
        edges.add((src, dst))
        nodes.add(src)
        nodes.add(dst)

    return nodes, edges


def build_graph_from_sdsm(
    path: str, include_tests: bool, edge_kinds: Set[str]
) -> nx.DiGraph:
    nodes, edges = load_edges_from_sdsm(path, include_tests, edge_kinds)
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    G.add_edges_from(edges)
    return G


def nontrivial_sccs(G: nx.DiGraph) -> List[set]:
    """List SCCs with size > 1, largest first."""
    sccs = [set(s) for s in nx.strongly_connected_components(G) if len(s) > 1]
    return sorted(sccs, key=len, reverse=True)


def scc_metrics(G: nx.DiGraph) -> dict:
    """Project-level SCC metrics including a 'cycle_pressure_lb' lower bound."""
    sccs = nontrivial_sccs(G)
    metrics = {
        "scc_count": len(sccs),
        "total_nodes_in_cyclic_sccs": 0,
        "total_edges_in_cyclic_sccs": 0,
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
        metrics["sccs"].append(
            {
                "size": n,
                "edge_count": m,
                "density_directed": round(dens, 4),
                "edge_surplus_lb": edge_surplus_lb,
            }
        )
        metrics["total_nodes_in_cyclic_sccs"] += n
        metrics["total_edges_in_cyclic_sccs"] += m

    metrics["max_scc_size"] = max(sizes)
    metrics["avg_scc_size"] = round(sum(sizes) / len(sizes), 2)
    metrics["cycle_pressure_lb"] = sum(s["edge_surplus_lb"] for s in metrics["sccs"])
    return metrics
