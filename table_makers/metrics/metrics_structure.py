from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.io_utils import path_exists, read_json

Edge = Tuple[str, str]


def parse_graph_edges(graph_path: Path) -> Optional[Set[Edge]]:
    if not path_exists(graph_path):
        return None

    data = read_json(graph_path)
    edges_raw = data.get("edges", [])
    if not isinstance(edges_raw, list):
        return None

    out: Set[Edge] = set()
    for e in edges_raw:
        if not isinstance(e, dict):
            continue
        src = e.get("source")
        dst = e.get("target")
        if isinstance(src, str) and isinstance(dst, str):
            out.add((src, dst))
    return out


def parse_graph_nodes_from_edges(edges: Set[Edge]) -> Set[str]:
    nodes: Set[str] = set()
    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)
    return nodes


def build_adj(edges: Set[Edge], restrict_to: Optional[Set[str]] = None) -> Dict[str, Set[str]]:
    adj: Dict[str, Set[str]] = {}
    nodes = parse_graph_nodes_from_edges(edges)

    if restrict_to is not None:
        nodes = {n for n in nodes if n in restrict_to}

    for node in nodes:
        adj[node] = set()

    for src, dst in edges:
        if restrict_to is not None and (src not in restrict_to or dst not in restrict_to):
            continue
        adj.setdefault(src, set()).add(dst)
        adj.setdefault(dst, set())

    return adj


def strongly_connected_components(
    edges: Set[Edge],
    restrict_to: Optional[Set[str]] = None,
) -> List[Set[str]]:
    adj = build_adj(edges, restrict_to=restrict_to)
    index = 0
    index_map: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    stack: List[str] = []
    on_stack: Set[str] = set()
    out: List[Set[str]] = []

    sys.setrecursionlimit(max(2000, len(adj) * 4 + 100))

    def strongconnect(v: str) -> None:
        nonlocal index
        index_map[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, set()):
            if w not in index_map:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index_map[w])

        if lowlink[v] == index_map[v]:
            comp: Set[str] = set()
            while True:
                w = stack.pop()
                on_stack.remove(w)
                comp.add(w)
                if w == v:
                    break
            out.append(comp)

    for v in adj:
        if v not in index_map:
            strongconnect(v)

    return out


def is_cyclic_component(component: Set[str], edges: Set[Edge]) -> bool:
    if len(component) > 1:
        return True
    only = next(iter(component))
    return (only, only) in edges


def cyclic_components(
    edges: Set[Edge],
    restrict_to: Optional[Set[str]] = None,
) -> List[Set[str]]:
    return [
        comp
        for comp in strongly_connected_components(edges, restrict_to=restrict_to)
        if is_cyclic_component(comp, edges)
    ]


def component_internal_edge_count(edges: Set[Edge], component: Set[str]) -> int:
    return sum(1 for (s, t) in edges if s in component and t in component)


def component_redundancy(edges: Set[Edge], component: Set[str]) -> int:
    if not component:
        return 0
    m = component_internal_edge_count(edges, component)
    n = len(component)
    return max(0, m - n)


def sum_cyclic_redundancy(edges: Set[Edge], components: List[Set[str]]) -> int:
    return sum(component_redundancy(edges, comp) for comp in components)


def parse_baseline_scc_id(cycle_id: str) -> Optional[str]:
    match = re.match(r"^(scc_\d+)_cycle_\d+$", cycle_id)
    if not match:
        return None
    return match.group(1)


def extract_scc_nodes_from_report(scc_report: Dict[str, Any], scc_id: str) -> Optional[Set[str]]:
    sccs = scc_report.get("sccs", [])
    if not isinstance(sccs, list):
        return None

    for scc in sccs:
        if not isinstance(scc, dict):
            continue
        if scc.get("id") != scc_id:
            continue

        nodes_raw = scc.get("nodes", [])
        out: Set[str] = set()
        for node in nodes_raw:
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                out.add(node["id"])
            elif isinstance(node, str):
                out.add(node)

        return out if out else None

    return None


def extract_all_cyclic_nodes_from_scc_report(scc_report: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    sccs = scc_report.get("sccs", [])
    if not isinstance(sccs, list):
        return out

    for scc in sccs:
        if not isinstance(scc, dict):
            continue

        size = int(scc.get("size", 0) or 0)
        edges_raw = scc.get("edges", [])
        has_self_loop = any(
            isinstance(e, dict) and e.get("source") == e.get("target")
            for e in (edges_raw if isinstance(edges_raw, list) else [])
        )

        if size <= 1 and not has_self_loop:
            continue

        nodes_raw = scc.get("nodes", [])
        for node in nodes_raw:
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                out.add(node["id"])
            elif isinstance(node, str):
                out.add(node)

    return out


def sum_cyclic_redundancy_from_scc_report(scc_report: Dict[str, Any]) -> int:
    total = 0
    sccs = scc_report.get("sccs", [])
    if not isinstance(sccs, list):
        return 0

    for scc in sccs:
        if not isinstance(scc, dict):
            continue

        size = int(scc.get("size", 0) or 0)
        edge_count = int(scc.get("edge_count", 0) or 0)

        if size > 1:
            total += max(0, edge_count - size)
        elif size == 1:
            edges_raw = scc.get("edges", [])
            has_self_loop = any(
                isinstance(e, dict) and e.get("source") == e.get("target")
                for e in (edges_raw if isinstance(edges_raw, list) else [])
            )
            if has_self_loop:
                total += max(0, edge_count - 1)

    return total


def find_cycle_record_recursive(obj: Any, cycle_id: str) -> Optional[Dict[str, Any]]:
    if isinstance(obj, dict):
        if obj.get("id") == cycle_id:
            return obj
        for value in obj.values():
            found = find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    elif isinstance(obj, list):
        for value in obj:
            found = find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    return None


def normalize_node_list(values: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(values, list):
        return out

    for item in values:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            out.append(item["id"])

    return out


def normalize_edge_list(values: Any) -> List[Edge]:
    out: List[Edge] = []
    if not isinstance(values, list):
        return out

    for item in values:
        if isinstance(item, dict):
            src = item.get("source")
            dst = item.get("target")
            if isinstance(src, str) and isinstance(dst, str):
                out.append((src, dst))
        elif (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], str)
        ):
            out.append((item[0], item[1]))

    return out


def infer_cycle_edges_from_nodes(nodes: List[str]) -> List[Edge]:
    if len(nodes) < 2:
        return []

    out: List[Edge] = []
    for i in range(len(nodes)):
        out.append((nodes[i], nodes[(i + 1) % len(nodes)]))
    return out


def extract_cycle_edges(cycle_catalog_path: Path, cycle_id: str) -> Optional[Set[Edge]]:
    if not path_exists(cycle_catalog_path):
        return None

    catalog = read_json(cycle_catalog_path)
    record = find_cycle_record_recursive(catalog, cycle_id)
    if record is None:
        return None

    for key in ("edges", "cycle_edges"):
        edges = normalize_edge_list(record.get(key))
        if edges:
            return set(edges)

    for key in ("nodes", "cycle_nodes", "path", "files"):
        nodes = normalize_node_list(record.get(key))
        if nodes:
            inferred = infer_cycle_edges_from_nodes(nodes)
            if inferred:
                return set(inferred)

    return None


def _baseline_local_redundancy_for_scc(
    baseline_scc_report: Dict[str, Any],
    baseline_scc_id: str,
) -> int:
    sccs = baseline_scc_report.get("sccs", [])
    if not isinstance(sccs, list):
        return 0

    for scc in sccs:
        if isinstance(scc, dict) and scc.get("id") == baseline_scc_id:
            size = int(scc.get("size", 0) or 0)
            edge_count = int(scc.get("edge_count", 0) or 0)
            return max(0, edge_count - size)

    return 0


def compute_structural_metrics(
    baseline_graph_path: Path,
    baseline_scc_report_path: Path,
    baseline_cycle_catalog_path: Path,
    post_scc_report_path: Path,
    post_graph_path: Path,
    cycle_id: str,
    no_change: bool = False,
) -> Dict[str, Any]:
    has_baseline_graph = path_exists(baseline_graph_path)
    has_baseline_scc_report = path_exists(baseline_scc_report_path)
    has_baseline_cycle_catalog = path_exists(baseline_cycle_catalog_path)
    has_post_scc_report = path_exists(post_scc_report_path)
    has_post_graph = path_exists(post_graph_path)

    normal_structurally_evaluable = (
        has_baseline_scc_report
        and has_baseline_cycle_catalog
        and has_post_scc_report
        and has_post_graph
    )

    no_change_structurally_evaluable = (
        no_change
        and has_baseline_graph
        and has_baseline_scc_report
        and has_baseline_cycle_catalog
    )

    structurally_evaluable = normal_structurally_evaluable or no_change_structurally_evaluable

    defaults: Dict[str, Any] = {
        "structurally_evaluable": structurally_evaluable,
        "cycle_eliminated_raw": False,
        "structural_improvement_raw": False,
        "weakening_improvement_raw": False,
        "global_structural_regression_raw": False,
        "global_regression_outside_target_raw": False,
        "baseline_local_redundancy": 0,
        "post_local_redundancy": 0,
        "post_witness_region_component_count": 0,
        "baseline_global_redundancy": 0,
        "post_global_redundancy": 0,
        "has_baseline_scc_report": has_baseline_scc_report,
        "has_post_scc_report": has_post_scc_report,
        "has_baseline_cycle_catalog": has_baseline_cycle_catalog,
        "has_post_graph": has_post_graph,
    }

    if not has_baseline_scc_report or not has_baseline_cycle_catalog:
        return defaults

    if no_change_structurally_evaluable and not normal_structurally_evaluable:
        baseline_scc_report = read_json(baseline_scc_report_path)
        baseline_edges = parse_graph_edges(baseline_graph_path)
        if baseline_edges is None:
            return defaults

        baseline_scc_id = parse_baseline_scc_id(cycle_id)
        if baseline_scc_id is None:
            return defaults

        original_nodes = extract_scc_nodes_from_report(baseline_scc_report, baseline_scc_id)
        if not original_nodes:
            return defaults

        baseline_local_redundancy = _baseline_local_redundancy_for_scc(
            baseline_scc_report=baseline_scc_report,
            baseline_scc_id=baseline_scc_id,
        )

        baseline_global_redundancy = sum_cyclic_redundancy_from_scc_report(baseline_scc_report)
        baseline_cyclic_sccs = cyclic_components(baseline_edges)
        overlapping_baseline_cyclic_sccs = [
            comp for comp in baseline_cyclic_sccs if not comp.isdisjoint(original_nodes)
        ]

        return {
            "structurally_evaluable": True,
            "cycle_eliminated_raw": False,
            "structural_improvement_raw": False,
            "weakening_improvement_raw": False,
            "global_structural_regression_raw": False,
            "global_regression_outside_target_raw": False,
            "baseline_local_redundancy": baseline_local_redundancy,
            "post_local_redundancy": baseline_local_redundancy,
            "post_witness_region_component_count": len(overlapping_baseline_cyclic_sccs),
            "baseline_global_redundancy": baseline_global_redundancy,
            "post_global_redundancy": baseline_global_redundancy,
            "has_baseline_scc_report": has_baseline_scc_report,
            "has_post_scc_report": has_post_scc_report,
            "has_baseline_cycle_catalog": has_baseline_cycle_catalog,
            "has_post_graph": has_post_graph,
        }

    if not normal_structurally_evaluable:
        return defaults

    baseline_scc_report = read_json(baseline_scc_report_path)
    post_scc_report = read_json(post_scc_report_path)
    post_edges = parse_graph_edges(post_graph_path)
    if post_edges is None:
        return defaults

    baseline_scc_id = parse_baseline_scc_id(cycle_id)
    if baseline_scc_id is None:
        return defaults

    original_nodes = extract_scc_nodes_from_report(baseline_scc_report, baseline_scc_id)
    if not original_nodes:
        return defaults

    cycle_edges = extract_cycle_edges(baseline_cycle_catalog_path, cycle_id)
    cycle_eliminated_raw = False
    if cycle_edges:
        cycle_eliminated_raw = any(edge not in post_edges for edge in cycle_edges)

    baseline_local_redundancy = _baseline_local_redundancy_for_scc(
        baseline_scc_report=baseline_scc_report,
        baseline_scc_id=baseline_scc_id,
    )

    post_cyclic_sccs = cyclic_components(post_edges)
    overlapping_post_cyclic_sccs = [
        comp for comp in post_cyclic_sccs if not comp.isdisjoint(original_nodes)
    ]
    post_witness_region_component_count = len(overlapping_post_cyclic_sccs)
    post_local_redundancy = sum_cyclic_redundancy(post_edges, overlapping_post_cyclic_sccs)

    structural_improvement_raw = (
        post_witness_region_component_count != 1
        and post_local_redundancy < baseline_local_redundancy
    )
    weakening_improvement_raw = (
        post_witness_region_component_count == 1
        and post_local_redundancy < baseline_local_redundancy
    )

    baseline_global_redundancy = sum_cyclic_redundancy_from_scc_report(baseline_scc_report)
    post_global_redundancy = sum_cyclic_redundancy_from_scc_report(post_scc_report)

    baseline_cyclic_nodes = extract_all_cyclic_nodes_from_scc_report(baseline_scc_report)
    post_cyclic_nodes = extract_all_cyclic_nodes_from_scc_report(post_scc_report)

    global_regression_outside_target_raw = any(
        (node not in original_nodes) and (node not in baseline_cyclic_nodes)
        for node in post_cyclic_nodes
    )

    global_structural_regression_raw = (
        post_global_redundancy > baseline_global_redundancy
        or global_regression_outside_target_raw
    )

    return {
        "structurally_evaluable": structurally_evaluable,
        "cycle_eliminated_raw": cycle_eliminated_raw,
        "structural_improvement_raw": structural_improvement_raw,
        "weakening_improvement_raw": weakening_improvement_raw,
        "global_structural_regression_raw": global_structural_regression_raw,
        "global_regression_outside_target_raw": global_regression_outside_target_raw,
        "baseline_local_redundancy": baseline_local_redundancy,
        "post_local_redundancy": post_local_redundancy,
        "post_witness_region_component_count": post_witness_region_component_count,
        "baseline_global_redundancy": baseline_global_redundancy,
        "post_global_redundancy": post_global_redundancy,
        "has_baseline_scc_report": has_baseline_scc_report,
        "has_post_scc_report": has_post_scc_report,
        "has_baseline_cycle_catalog": has_baseline_cycle_catalog,
        "has_post_graph": has_post_graph,
    }