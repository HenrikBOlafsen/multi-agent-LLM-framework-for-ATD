#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys, ast
from typing import Dict, List, Tuple, Set
from functools import lru_cache
import importlib.machinery
import networkx as nx

# ---------------------------------------------------------------------------
# pydeps JSON loader
# ---------------------------------------------------------------------------

def load_pydeps(pydeps_json: str) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """
    Normalize pydeps JSON to (imports, paths).
    Supports:
      1) {"imports": {"a.b": ["c.d", ...], ...}}
      2) {"a.b": {"imports": [...], "path": "..."} , ...}
    """
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

def _module_to_file(mod: str, paths: Dict[str, str], top_pkg: str) -> str | None:
    """Prefer pydeps path; else accept path-like; else bounded spec for our top_pkg namespace."""
    p = paths.get(mod)
    if p:
        return p
    if _is_path_like(mod):
        return mod
    if top_pkg and (mod == top_pkg or mod.startswith(top_pkg + ".")):
        return _safe_find_spec(mod)
    return None

def _repo_rel(path: str, root: str) -> str:
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace("\\", "/")

# ---------------------------------------------------------------------------
# Source analysis (TYPE_CHECKING filter + proper relative resolution)
# ---------------------------------------------------------------------------

def _expr_has_type_checking(test: ast.AST) -> bool:
    """Heuristic: does the condition reference TYPE_CHECKING (typing.TYPE_CHECKING or bare)?"""
    class Finder(ast.NodeVisitor):
        found = False
        def visit_Name(self, n: ast.Name):
            if n.id == "TYPE_CHECKING":
                self.found = True
        def visit_Attribute(self, n: ast.Attribute):
            if n.attr == "TYPE_CHECKING":
                self.found = True
            self.generic_visit(n)
    f = Finder()
    try:
        f.visit(test)
    except Exception:
        return False
    return f.found

def _resolve_from_target(cur_mod: str, level: int, module: str | None) -> str | None:
    """
    Resolve a 'from' import target to an absolute dotted module name.
    Examples (cur_mod='kombu.transport.redis'):
      level=1, module='utils'   -> 'kombu.transport.utils'
      level=2, module='common'  -> 'kombu.common'
      level=1, module=None      -> 'kombu.transport'   (i.e., 'from . import X')
    """
    parts = cur_mod.split(".")
    if level > 0:
        if level > len(parts):
            return None
        base = parts[:-level]
    else:
        base = parts
    if module:
        return ".".join([*base, module]) if base else module
    return ".".join(base) if base else None

def _imports_excluding_type_checking(abs_path: str, cur_mod: str) -> Set[str]:
    """
    Collect module names imported anywhere in the file, excluding those nested under
    an `if TYPE_CHECKING:` guard. Returns absolute dotted module names.
    - Handles 'import X' (adds X)
    - Handles 'from Y import Z' (adds Y, resolved for relative forms)
    """
    out: Set[str] = set()
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        tree = ast.parse(src, filename=abs_path)
    except Exception:
        return out

    def visit(node: ast.AST, under_tc: bool = False):
        tc_here = isinstance(node, ast.If) and _expr_has_type_checking(node.test)
        now_tc = under_tc or tc_here

        if isinstance(node, ast.Import):
            if not now_tc:
                for a in node.names:
                    if a.name:
                        out.add(a.name)

        elif isinstance(node, ast.ImportFrom):
            if not now_tc:
                target = None
                try:
                    target = _resolve_from_target(cur_mod, getattr(node, "level", 0) or 0, node.module)
                except Exception:
                    target = node.module  # best-effort
                if target:
                    out.add(target)

        for child in ast.iter_child_nodes(node):
            visit(child, now_tc)

    visit(tree, False)
    return out

# ---------------------------------------------------------------------------
# Graph builder (NO __init__ filtering at all)
# ---------------------------------------------------------------------------

def build_graph_from_pydeps(pydeps_json: str, repo_root: str) -> nx.DiGraph:
    """
    Resolve each module once, keep only files inside repo_root, then connect edges.

    Filtering applied:
      • drop an edge if the source import only appears under TYPE_CHECKING in source
    """
    imports, paths = load_pydeps(pydeps_json)
    root = os.path.realpath(repo_root)
    top_pkg = os.getenv("PACKAGE_NAME", "")

    # Map module -> abs path (filtered to repo)
    mod_abs: Dict[str, str] = {}
    for mod in imports.keys():
        p = _module_to_file(mod, paths, top_pkg)
        if not p:
            continue
        rp = os.path.realpath(p)
        if rp.startswith(root):
            mod_abs[mod] = rp

    # Repo-relative node key
    mod_key: Dict[str, str] = {m: _repo_rel(p, root) for m, p in mod_abs.items()}

    # Precompute per-file imported modules excluding TYPE_CHECKING (with relative resolution)
    imports_no_tc_by_file: Dict[str, Set[str]] = {}
    for m, abs_p in mod_abs.items():
        key = mod_key[m]
        imports_no_tc_by_file[key] = _imports_excluding_type_checking(abs_p, m)

    # Build edges (no __init__ special-casing)
    edges: list[tuple[str, str]] = []
    for src_mod, deps in imports.items():
        skey = mod_key.get(src_mod)
        if not skey:
            continue

        src_seen = imports_no_tc_by_file.get(skey, set())

        for dmod in deps or []:
            dkey = mod_key.get(dmod)
            if not dkey or dkey == skey:
                continue

            # Require the source file (outside TYPE_CHECKING) to mention the target's module
            # or one of its package prefixes/suffixes.
            if src_seen:
                keep = any(
                    dmod == s or dmod.startswith(s + ".") or s.startswith(dmod + ".")
                    for s in src_seen
                )
                if not keep:
                    continue

            edges.append((skey, dkey))

    G = nx.DiGraph()
    G.add_nodes_from(mod_key.values())
    G.add_edges_from(edges)

    # Attach absolute paths for later LOC/metrics
    abs_map = {mod_key[m]: mod_abs[m] for m in mod_key.keys()}
    for n in G.nodes():
        G.nodes[n]["abs_path"] = abs_map.get(n, os.path.join(root, n))
    G.graph["repo_root"] = root
    return G

# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

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
        "total_edges_in_cclic_sccs": 0,
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
        metrics["total_edges_in_cclic_sccs"] += m
        metrics["total_loc_in_cyclic_sccs"] += total_loc

    metrics["max_scc_size"] = max(sizes)
    metrics["avg_scc_size"] = round(sum(sizes) / len(sizes), 2)
    metrics["cycle_pressure_lb"] = sum(s["edge_surplus_lb"] for s in metrics["sccs"])
    return metrics
