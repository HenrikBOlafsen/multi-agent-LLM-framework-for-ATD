#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.dataset_builder import build_all_runs_dataframe
from metrics.metrics_difficulty import add_difficulty_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dev", required=True)
    parser.add_argument("--analysis-plan-dev", required=True)
    parser.add_argument("--config-eval", required=True)
    parser.add_argument("--analysis-plan-eval", required=True)
    parser.add_argument("--top", type=int, default=10)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cycles(config_path: Path, analysis_plan_path: Path, split: str) -> pd.DataFrame:
    df = build_all_runs_dataframe(
        config_path=config_path.resolve(),
        analysis_plan_path=analysis_plan_path.resolve(),
    )
    df = add_difficulty_metrics(df)

    cycles = (
        df[
            [
                "repo",
                "cycle_id",
                "language",
                "cycle_size",
                "cycle_centrality",
                "baseline_scc_size",
                "baseline_scc_redundancy",
                "baseline_scc_external_edges",
                "repo_dependency_graph_size",
                "cycle_external_edges",
                "baseline_graph_path",
                "baseline_cycle_catalog_path",
            ]
        ]
        .drop_duplicates(subset=["repo", "cycle_id"])
        .copy()
    )

    cycles["split"] = split

    for col in [
        "cycle_size",
        "cycle_centrality",
        "baseline_scc_size",
        "baseline_scc_redundancy",
        "baseline_scc_external_edges",
        "repo_dependency_graph_size",
        "cycle_external_edges",
    ]:
        cycles[col] = pd.to_numeric(cycles[col], errors="coerce")

    return cycles


def find_cycle_record_recursive(obj: Any, cycle_id: str) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        if obj.get("id") == cycle_id:
            return obj
        for value in obj.values():
            found = find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    if isinstance(obj, list):
        for value in obj:
            found = find_cycle_record_recursive(value, cycle_id)
            if found is not None:
                return found

    return None


def normalize_nodes(record: dict[str, Any]) -> list[str]:
    for key in ["nodes", "cycle_nodes", "path", "files"]:
        raw = record.get(key)
        if isinstance(raw, list):
            out = []
            for item in raw:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict) and isinstance(item.get("id"), str):
                    out.append(item["id"])
            if out:
                return out

    raw_edges = record.get("edges") or record.get("cycle_edges")
    if isinstance(raw_edges, list):
        nodes = []
        seen = set()
        for edge in raw_edges:
            if isinstance(edge, dict):
                src = edge.get("source")
                dst = edge.get("target")
            elif isinstance(edge, list | tuple) and len(edge) == 2:
                src, dst = edge
            else:
                continue

            for node in [src, dst]:
                if isinstance(node, str) and node not in seen:
                    seen.add(node)
                    nodes.append(node)

        return nodes

    return []


def normalize_edges(graph: dict[str, Any]) -> list[tuple[str, str]]:
    edges = []
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        dst = edge.get("target")
        if isinstance(src, str) and isinstance(dst, str):
            edges.append((src, dst))
    return edges


def inspect_cycle(row: pd.Series) -> None:
    repo = str(row["repo"])
    cycle_id = str(row["cycle_id"])

    graph_path = Path(str(row["baseline_graph_path"]))
    catalog_path = Path(str(row["baseline_cycle_catalog_path"]))

    graph = read_json(graph_path)
    catalog = read_json(catalog_path)

    record = find_cycle_record_recursive(catalog, cycle_id)
    if record is None:
        print(f"\nCould not find cycle record for {repo} {cycle_id}")
        return

    cycle_nodes = set(normalize_nodes(record))
    edges = normalize_edges(graph)

    outgoing = [(src, dst) for src, dst in edges if src in cycle_nodes and dst not in cycle_nodes]
    incoming = [(src, dst) for src, dst in edges if src not in cycle_nodes and dst in cycle_nodes]
    internal = [(src, dst) for src, dst in edges if src in cycle_nodes and dst in cycle_nodes]

    print("\n" + "=" * 88)
    print(f"Repo:                    {repo}")
    print(f"Split:                   {row['split']}")
    print(f"Language:                {row['language']}")
    print(f"Cycle id:                {cycle_id}")
    print(f"Cycle size:              {int(row['cycle_size'])}")
    print(f"Cycle external edges:    {int(row['cycle_external_edges'])}")
    print(f"Incoming external edges: {len(incoming)}")
    print(f"Outgoing external edges: {len(outgoing)}")
    print(f"Internal cycle/SCC edges among cycle files: {len(internal)}")
    print(f"Enclosing SCC size:      {int(row['baseline_scc_size'])}")
    print(f"Enclosing SCC redundancy:{int(row['baseline_scc_redundancy'])}")
    print(f"Repo graph size:         {int(row['repo_dependency_graph_size'])}")
    print(f"Graph path:              {graph_path}")
    print(f"Catalog path:            {catalog_path}")

    print("\nCycle nodes:")
    for node in sorted(cycle_nodes):
        print(f"  - {node}")

    print("\nExternal degree by cycle node:")
    degree_rows = []
    for node in sorted(cycle_nodes):
        in_n = sum(1 for _src, dst in incoming if dst == node)
        out_n = sum(1 for src, _dst in outgoing if src == node)
        degree_rows.append((node, in_n, out_n, in_n + out_n))

    for node, in_n, out_n, total in sorted(degree_rows, key=lambda x: x[3], reverse=True):
        print(f"  - {node}: incoming={in_n}, outgoing={out_n}, total={total}")

    print("\nTop incoming external source files:")
    incoming_sources = pd.Series([src for src, _dst in incoming]).value_counts().head(20)
    if incoming_sources.empty:
        print("  None")
    else:
        for node, count in incoming_sources.items():
            print(f"  - {count:4d}  {node}")

    print("\nTop outgoing external target files:")
    outgoing_targets = pd.Series([dst for _src, dst in outgoing]).value_counts().head(20)
    if outgoing_targets.empty:
        print("  None")
    else:
        for node, count in outgoing_targets.items():
            print(f"  - {count:4d}  {node}")

    print("\nSample incoming external edges:")
    for src, dst in incoming[:25]:
        print(f"  - {src} -> {dst}")

    print("\nSample outgoing external edges:")
    for src, dst in outgoing[:25]:
        print(f"  - {src} -> {dst}")


def main() -> None:
    args = parse_args()

    dev = load_cycles(
        Path(args.config_dev),
        Path(args.analysis_plan_dev),
        "Development",
    )
    eval_ = load_cycles(
        Path(args.config_eval),
        Path(args.analysis_plan_eval),
        "Evaluation",
    )

    cycles = pd.concat([dev, eval_], ignore_index=True)

    ranked = (
        cycles.dropna(subset=["cycle_external_edges"])
        .sort_values("cycle_external_edges", ascending=False)
        .head(args.top)
    )

    print("\nTop cycles by external connectivity:")
    display_cols = [
        "split",
        "repo",
        "language",
        "cycle_id",
        "cycle_size",
        "cycle_external_edges",
        "baseline_scc_size",
        "repo_dependency_graph_size",
    ]
    print(ranked[display_cols].to_string(index=False))

    if ranked.empty:
        return

    inspect_cycle(ranked.iloc[0])


if __name__ == "__main__":
    main()