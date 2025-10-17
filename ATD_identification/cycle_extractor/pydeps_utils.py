#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys, importlib.machinery
from typing import Dict, List, Tuple
import networkx as nx

# -------- JSON normalization --------
def load_pydeps(pydeps_json: str) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    raw = json.load(open(pydeps_json, "r", encoding="utf-8"))
    if isinstance(raw, dict) and "imports" in raw and isinstance(raw["imports"], dict):
        imports = raw["imports"]
        paths: Dict[str, str] = {}
    else:
        imports = {m: (obj.get("imports") or []) for m, obj in raw.items() if isinstance(obj, dict)}
        paths   = {m: obj.get("path")            for m, obj in raw.items() if isinstance(obj, dict)}
    return imports, paths

# -------- path helpers --------
def is_path_like(s: str) -> bool:
    return isinstance(s, str) and ("/" in s or "\\" in s) and s.endswith(".py")

def module_to_file(mod: str, paths: Dict[str, str]) -> str | None:
    """Prefer pydeps-provided path; else accept path-like keys; else resolve safely."""
    p = paths.get(mod)
    if p:
        return p
    if is_path_like(mod):
        return mod
    try:
        spec = importlib.machinery.PathFinder.find_spec(mod, sys.path)
        if spec and getattr(spec, "origin", None) and spec.origin != "built-in":
            return spec.origin
    except Exception:
        pass
    return None

def repo_rel(path: str, root: str) -> str:
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace("\\", "/")

# -------- graph build --------
def build_graph_from_pydeps(pydeps_json: str, repo_root: str) -> nx.DiGraph:
    imports, paths = load_pydeps(pydeps_json)
    root = os.path.realpath(repo_root)

    G = nx.DiGraph()
    abs_map: Dict[str, str] = {}  # key (repo-rel) -> absolute file path
    miss_src = miss_dst = 0

    for src_mod, deps in imports.items():
        src_path = module_to_file(src_mod, paths)
        if not src_path:
            miss_src += 1
            continue
        rsrc = os.path.realpath(src_path)
        if not rsrc.startswith(root):
            continue
        src_key = repo_rel(rsrc, root)
        abs_map[src_key] = rsrc

        for dst_mod in deps or []:
            dst_path = module_to_file(dst_mod, paths)
            if not dst_path:
                miss_dst += 1
                continue
            rdst = os.path.realpath(dst_path)
            if not rdst.startswith(root):
                continue
            dst_key = repo_rel(rdst, root)
            abs_map[dst_key] = rdst
            if src_key != dst_key:
                G.add_edge(src_key, dst_key)

    # Attach attributes: use the absolute path we recorded (no re-joining)
    for n in G.nodes():
        abs_path = abs_map.get(n, os.path.join(root, n))
        G.nodes[n]["abs_path"] = abs_path
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                G.nodes[n]["loc"] = sum(1 for line in f if line.strip())
        except (FileNotFoundError, IsADirectoryError):
            G.nodes[n]["loc"] = 0

    G.graph["repo_root"] = root
    # Optional debug:
    # print(f"[pydeps_utils] nodes={G.number_of_nodes()} edges={G.number_of_edges()} miss_src={miss_src} miss_dst={miss_dst}", file=sys.stderr)
    return G

# -------- SCC helpers (shared) --------
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
        sub = G.subgraph(s).copy()
        n = sub.number_of_nodes(); m = sub.number_of_edges()
        sizes.append(n)
        dens = m / (n * (n - 1)) if n > 1 else 0.0
        und = sub.to_undirected(); m_und = und.number_of_edges()
        edge_surplus_lb = max(0, m_und - (n - 1))
        total_loc = sum(int(G.nodes[u].get("loc", 0)) for u in s)
        metrics["sccs"].append({
            "size": n,
            "edge_count": m,
            "density_directed": round(dens, 4),
            "edge_surplus_lb": edge_surplus_lb,
            "total_loc": total_loc,
            "avg_loc_per_node": round(total_loc / n, 1),
        })
        metrics["total_nodes_in_cyclic_sccs"] += n
        metrics["total_edges_in_cyclic_sccs"] += m
        metrics["total_loc_in_cyclic_sccs"] += total_loc

    metrics["max_scc_size"] = max(sizes)
    metrics["avg_scc_size"] = round(sum(sizes) / len(sizes), 2)
    metrics["cycle_pressure_lb"] = sum(s["edge_surplus_lb"] for s in metrics["sccs"])
    return metrics
