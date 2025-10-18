#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from typing import Dict, List, Tuple
from functools import lru_cache
import importlib.machinery
import networkx as nx

def load_pydeps(pydeps_json: str) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """Normalize pydeps JSON to (imports, paths)."""
    raw = json.load(open(pydeps_json, "r", encoding="utf-8"))
    if isinstance(raw, dict) and "imports" in raw and isinstance(raw["imports"], dict):
        return raw["imports"], {}
    imports = {m: (obj.get("imports") or []) for m, obj in raw.items() if isinstance(obj, dict)}
    paths   = {m: obj.get("path")            for m, obj in raw.items() if isinstance(obj, dict)}
    return imports, paths

def _is_path_like(s: str) -> bool:
    return isinstance(s, str) and ("/" in s or "\\" in s) and s.endswith(".py")

@lru_cache(maxsize=None)
def _safe_find_spec(mod: str) -> str | None:
    try:
        spec = importlib.machinery.PathFinder.find_spec(mod, sys.path)
        if spec and getattr(spec, "origin", None) and spec.origin != "built-in":
            return spec.origin
    except Exception:
        pass
    return None

def _module_to_file(mod: str, paths: Dict[str, str], pkg: str) -> str | None:
    """Prefer pydeps path; else accept path-like mod; else bounded spec for our package names."""
    p = paths.get(mod)
    if p:
        return p
    if _is_path_like(mod):
        return mod
    if pkg and (mod == pkg or mod.startswith(pkg + ".")):
        return _safe_find_spec(mod)
    return None

def _repo_rel(path: str, root: str) -> str:
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace("\\", "/")

def build_graph_from_pydeps(pydeps_json: str, repo_root: str) -> nx.DiGraph:
    """
    Resolve each module once, keep only files inside repo_root, then connect edges via dict lookups.
    Assumes pydeps was run with --only "$PKG_NAME" to avoid externals in the first place.
    """
    imports, paths = load_pydeps(pydeps_json)
    root = os.path.realpath(repo_root)
    pkg  = os.getenv("PACKAGE_NAME", "")

    # Map module -> abs path (filtered to repo)
    mod_abs: Dict[str, str] = {}
    for mod in imports.keys():
        p = _module_to_file(mod, paths, pkg)
        if not p:
            continue
        rp = os.path.realpath(p)
        if rp.startswith(root):
            mod_abs[mod] = rp

    # Map module -> repo key
    mod_key: Dict[str, str] = {m: _repo_rel(p, root) for m, p in mod_abs.items()}

    # Edges
    edges = []
    for src_mod, deps in imports.items():
        skey = mod_key.get(src_mod)
        if not skey:
            continue
        for dmod in deps or []:
            dkey = mod_key.get(dmod)
            if dkey and dkey != skey:
                edges.append((skey, dkey))

    G = nx.DiGraph()
    G.add_nodes_from(mod_key.values())
    G.add_edges_from(edges)

    # Attach abs_path for LOC later
    abs_map = {mod_key[m]: mod_abs[m] for m in mod_key.keys()}
    for n in G.nodes():
        G.nodes[n]["abs_path"] = abs_map.get(n, os.path.join(root, n))
    G.graph["repo_root"] = root
    return G

# ---- metrics helpers (LOC counted only for SCC nodes) ----
from functools import lru_cache as _lru

@_lru(maxsize=None)
def _count_loc(abs_path: str) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except (FileNotFoundError, IsADirectoryError):
        return 0

def nontrivial_sccs(G: nx.DiGraph):
    return [set(s) for s in nx.strongly_connected_components(G) if len(s) > 1]

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
        total_loc = sum(_count_loc(G.nodes[u].get("abs_path", "")) for u in s)

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
