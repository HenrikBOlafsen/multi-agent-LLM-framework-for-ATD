from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

Edge = Tuple[str, str]


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _parse_baseline_scc_id(cycle_id: str) -> Optional[str]:
    match = re.match(r"^(scc_\d+)_cycle_\d+$", str(cycle_id))
    if not match:
        return None
    return match.group(1)


def _find_cycle_record_recursive(obj: Any, cycle_id: str) -> Optional[Dict[str, Any]]:
    if isinstance(obj, dict):
        if obj.get("id") == cycle_id:
            return obj
        for value in obj.values():
            found = _find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    elif isinstance(obj, list):
        for value in obj:
            found = _find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    return None


def _normalize_node_list(values: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(values, list):
        return out

    for item in values:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            out.append(item["id"])

    return out


def _normalize_edge_list(values: Any) -> List[Edge]:
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


def _extract_cycle_nodes(cycle_catalog_path: Path, cycle_id: str) -> Set[str]:
    data = _read_json(cycle_catalog_path)
    if data is None:
        return set()

    record = _find_cycle_record_recursive(data, cycle_id)
    if record is None:
        return set()

    for key in ("nodes", "cycle_nodes", "path", "files"):
        nodes = _normalize_node_list(record.get(key))
        if nodes:
            return set(nodes)

    for key in ("edges", "cycle_edges"):
        edges = _normalize_edge_list(record.get(key))
        if edges:
            nodes: Set[str] = set()
            for src, dst in edges:
                nodes.add(src)
                nodes.add(dst)
            return nodes

    return set()


def _parse_graph_edges(graph_path: Path) -> Set[Edge]:
    data = _read_json(graph_path)
    if data is None:
        return set()

    edges_raw = data.get("edges", [])
    if not isinstance(edges_raw, list):
        return set()

    out: Set[Edge] = set()
    for edge in edges_raw:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        dst = edge.get("target")
        if isinstance(src, str) and isinstance(dst, str):
            out.add((src, dst))

    return out


def _parse_graph_nodes(graph_path: Path, edges: Optional[Set[Edge]] = None) -> Set[str]:
    data = _read_json(graph_path)
    nodes: Set[str] = set()

    if data is not None:
        nodes_raw = data.get("nodes", [])
        if isinstance(nodes_raw, list):
            for node in nodes_raw:
                if isinstance(node, str):
                    nodes.add(node)
                elif isinstance(node, dict) and isinstance(node.get("id"), str):
                    nodes.add(node["id"])

    if edges is None:
        edges = _parse_graph_edges(graph_path)

    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)

    return nodes


def _extract_scc_record(scc_report: Dict[str, Any], scc_id: str) -> Optional[Dict[str, Any]]:
    sccs = scc_report.get("sccs", [])
    if not isinstance(sccs, list):
        return None

    for scc in sccs:
        if isinstance(scc, dict) and scc.get("id") == scc_id:
            return scc

    return None


def _extract_scc_nodes(scc_record: Dict[str, Any]) -> Set[str]:
    return set(_normalize_node_list(scc_record.get("nodes", [])))


def _pagerank(
    edges: Set[Edge],
    nodes: Set[str],
    *,
    damping: float = 0.85,
    iterations: int = 50,
) -> Dict[str, float]:
    if not nodes:
        return {}

    outgoing: Dict[str, Set[str]] = {node: set() for node in nodes}
    for src, dst in edges:
        if src in nodes and dst in nodes:
            outgoing[src].add(dst)

    n = len(nodes)
    ranks = {node: 1.0 / n for node in nodes}

    for _ in range(iterations):
        sink_rank = sum(ranks[node] for node in nodes if not outgoing[node])
        next_ranks = {
            node: (1.0 - damping) / n + damping * sink_rank / n
            for node in nodes
        }

        for src, targets in outgoing.items():
            if not targets:
                continue
            share = damping * ranks[src] / len(targets)
            for dst in targets:
                next_ranks[dst] += share

        ranks = next_ranks

    return ranks


def _safe_int(value: object) -> Optional[int]:
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _relative_cycle_pagerank(
    *,
    ranks: Dict[str, float],
    graph_nodes: Set[str],
    cycle_nodes: Set[str],
) -> Optional[float]:
    """
    Return cycle centrality as relative PageRank.

    Raw PageRank values are not directly comparable across repositories because
    PageRank mass sums to 1 within each graph. The uniform baseline for a graph
    with N nodes is 1/N. Therefore:

        relative centrality = mean_cycle_pagerank / (1 / N)
                            = N * mean_cycle_pagerank

    Interpretation:
        1.0 means the cycle nodes have average PageRank for that repository.
        2.0 means the cycle nodes have about twice average PageRank.
        0.5 means the cycle nodes have about half average PageRank.
    """
    if not ranks or not graph_nodes or not cycle_nodes:
        return None

    present_cycle_nodes = [node for node in cycle_nodes if node in ranks]
    if not present_cycle_nodes:
        return None

    mean_cycle_pagerank = (
        sum(ranks[node] for node in present_cycle_nodes)
        / len(present_cycle_nodes)
    )

    return len(graph_nodes) * mean_cycle_pagerank


def add_difficulty_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    key_cols = [
        "repo",
        "cycle_id",
        "baseline_graph_path",
        "baseline_scc_report_path",
        "baseline_cycle_catalog_path",
    ]

    rows: List[Dict[str, object]] = []

    for _, row in df[key_cols].drop_duplicates().iterrows():
        repo = str(row["repo"])
        cycle_id = str(row["cycle_id"])

        graph_path = Path(str(row["baseline_graph_path"]))
        scc_report_path = Path(str(row["baseline_scc_report_path"]))
        cycle_catalog_path = Path(str(row["baseline_cycle_catalog_path"]))

        edges = _parse_graph_edges(graph_path)
        graph_nodes = _parse_graph_nodes(graph_path, edges)
        repo_size = len(graph_nodes) if graph_nodes else None

        cycle_nodes = _extract_cycle_nodes(cycle_catalog_path, cycle_id)

        cycle_external_edges = None
        if cycle_nodes:
            cycle_external_edges = sum(
                1
                for src, dst in edges
                if (src in cycle_nodes and dst not in cycle_nodes)
                or (src not in cycle_nodes and dst in cycle_nodes)
            )

        ranks = _pagerank(edges, graph_nodes)
        cycle_centrality = _relative_cycle_pagerank(
            ranks=ranks,
            graph_nodes=graph_nodes,
            cycle_nodes=cycle_nodes,
        )

        scc_size = None
        scc_id = _parse_baseline_scc_id(cycle_id)
        scc_report = _read_json(scc_report_path)

        if scc_id is not None and scc_report is not None:
            scc_record = _extract_scc_record(scc_report, scc_id)
            if scc_record is not None:
                scc_nodes = _extract_scc_nodes(scc_record)
                scc_size = int(scc_record.get("size", len(scc_nodes)) or 0)

        rows.append(
            {
                "repo": repo,
                "cycle_id": cycle_id,
                "cycle_centrality": cycle_centrality,
                "baseline_scc_size": scc_size,
                "repo_dependency_graph_size": repo_size,
                "cycle_external_edges": cycle_external_edges,
            }
        )

    metrics_df = pd.DataFrame(rows)
    return df.merge(metrics_df, on=["repo", "cycle_id"], how="left")


def bin_cycle_centrality(value: object) -> Optional[str]:
    if pd.isna(value):
        return None

    x = float(value)

    if x <= 1.0:
        return "<=1x average"
    if x <= 2.0:
        return "1--2x average"
    return ">2x average"


def bin_cycle_external_edges(value: object) -> Optional[str]:
    n = _safe_int(value)
    if n is None:
        return None

    if n <= 50:
        return "<=50"
    if n <= 100:
        return "51--100"
    return ">100"


def bin_repo_size(value: object) -> Optional[str]:
    n = _safe_int(value)
    if n is None:
        return None

    if n <= 100:
        return "<=100"
    if n <= 300:
        return "101--300"
    return ">300"


def bin_fixed_scc_size(value: object) -> Optional[str]:
    n = _safe_int(value)
    if n is None:
        return None

    if n <= 10:
        return "1--10"
    if n <= 50:
        return "11--50"
    return ">50"


def sort_bin_label(label: object) -> int:
    text = str(label)

    order = {
        "<=1x average": 0,
        "1--2x average": 1,
        ">2x average": 2,
        "<=50": 0,
        "51--100": 1,
        ">100": 2,
        "<=100": 0,
        "101--300": 1,
        ">300": 2,
        "1--10": 0,
        "11--50": 1,
        ">50": 2,
    }

    return order.get(text, 999)