#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from typing import Dict, List, Tuple
import networkx as nx
from functools import lru_cache
import importlib.machinery

def load_pydeps(pydeps_json: str) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Normalize pydeps JSON to (imports, paths)."""
    raw = json.load(open(pydeps_json, "r", encoding="utf-8"))
    if isinstance(raw, dict) and "imports" in raw and isinstance(raw["imports"], dict):
        return raw["imports"], {}
    imports = {m: (obj.get("imports") or []) for m, obj in raw.items() if isinstance(obj, dict)}
    paths   = {m: obj.get("path")            for m, obj in raw.items() if isinstance(obj, dict)}
    return imports, paths

def is_path_like(s: str) -> bool:
    return isinstance(s, str) and ("/" in s or "\\" in s) and s.endswith(".py")

@lru_cache(maxsize=None)
def safe_find_spec(mod: str) -> str | None:
    try:
        spec = importlib.machinery.PathFinder.find_spec(mod, sys.path)
        if spec and getattr(spec, "origin", None) and spec.origin != "built-in":
            return spec.origin
    except Exception:
        pass
    return None

def module_to_file(mod: str, paths: Dict[str, str], package_name: str) -> str | None:
    """Prefer pydeps `path`; otherwise accept path-like keys; otherwise bounded spec lookup."""
    p = paths.get(mod)
    if p:
        return p
    if is_path_like(mod):
        return mod
    # Only try resolving names that look like they belong to our package.
    if package_name and (mod == package_name or mod.startswith(package_name + ".")):
        return safe_find_spec(mod)
    return None

def repo_rel(path: str, root: str) -> str:
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace("\\", "/")

def build_graph_from_pydeps(pydeps_json: str, repo_root: str) -> nx.DiGraph:
    """Fast graph build: resolve each module once, filter to repo, then connect via dict lookups."""
    imports, paths = load_pydeps(pydeps_json)
    root = os.path.realpath(repo_root)
    package_name = os.getenv("PACKAGE_NAME", "")

    # 1) module -> abs path (in repo only)
    mod_abs: Dict[str, str] = {}
    for mod in imports.keys():
        p = module_to_file(mod, paths, package_name)
        if not p:
            continue
        rp = os.path.realpath(p)
        if rp.startswith(root):
            mod_abs[mod] = rp

    # 2) module -> repo-relative key
    mod_key: Dict[str, str] = {m: repo_rel(p, root) for m, p in mod_abs.items()}

    # 3) edges via dict lookups (no per-edge I/O)
    edges = []
    for src_mod, deps in imports.items():
        skey = mod_key.get(src_mod)
        if not skey:
            continue
        for dmod in deps or []:
            dkey = mod_key.get(dmod)
            if not dkey or dkey == skey:
                continue
            edges.append((skey, dkey))

    # 4) graph + abs_path attributes (LOC handled elsewhere)
    G = nx.DiGraph()
    G.add_nodes_from(mod_key.values())
    G.add_edges_from(edges)

    abs_map = {mod_key[m]: mod_abs[m] for m in mod_key.keys()}
    for n in G.nodes():
        G.nodes[n]["abs_path"] = abs_map.get(n, os.path.join(root, n))

    G.graph["repo_root"] = root
    return G

# ---- SCC helpers & metrics (LOC computed only for SCC nodes) ----
from functools import lru_cache as _lru

def nontrivial_sccs(G: nx.DiGraph):
    return [set(s) for s in nx.strongly_connected_components(G) if len(s) > 1]

@_lru(maxsize=None)
def _count_loc(abs_path: str) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except (FileNotFoundError, IsADirectoryError):
        return 0

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

    sizes = []
    for s in sccs:
        sub = G.subgraph(s)  # view
        n = sub.number_of_nodes()
        m = sub.number_of_edges()
        sizes.append(n)
        dens = m / (n * (n - 1)) if n > 1 else 0.0
        m_und = sub.to_undirected(as_view=True).number_of_edges()
        edge_surplus_lb = max(0, m_und - (n - 1))

        total_loc = 0
        for u in s:
            ap = G.nodes[u].get("abs_path")
            if ap:
                total_loc += _count_loc(ap)

        metrics["sccs"].append({
            "size": n,
            "edge_count": m,
            "density_directed": round(dens, 4),
            "edge_surplus_lb": edge_surplus_lb,
            "total_loc": total_loc,
            "avg_loc_per_node": round(total_loc / n, 1) if n else 0.0,
        })
        metrics["total_nodes_in_cyclic_sccs"] += n
        metrics["total_edges_in_cyclic_sccs"] += m
        metrics["total_loc_in_cyclic_sccs"] += total_loc

    metrics["max_scc_size"] = max(sizes)
    metrics["avg_scc_size"] = round(sum(sizes) / len(sizes), 2)
    metrics["cycle_pressure_lb"] = sum(s["edge_surplus_lb"] for s in metrics["sccs"])
    return metrics
