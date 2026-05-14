#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Set, Tuple

import pandas as pd
import py4cytoscape as p4c


STYLE_NAME = "CycleSccSelectionStyle"


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_selected_cycles(path: Path, repo: str, branch: str) -> Set[str]:
    selected = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) == 3 and parts[0] == repo and parts[1] == branch:
            selected.add(parts[2])
    return selected


def edges_from_cycle(cycle: Dict[str, Any]) -> Set[Tuple[str, str]]:
    return {(e["source"], e["target"]) for e in cycle.get("edges", [])}


def short_label(path: str) -> str:
    name = Path(path).name
    if name == "__init__.py":
        return "__init__"
    return Path(path).stem


def ensure_cytoscape_running() -> None:
    try:
        p4c.cytoscape_ping()
    except Exception as e:
        raise RuntimeError("Cytoscape is not running.") from e


def apply_layout() -> str | None:
    layouts = {name.lower(): name for name in p4c.get_layout_names()}

    if "force-directed" in layouts:
        name = layouts["force-directed"]
        props = set(p4c.get_layout_property_names(name))

        chosen_props = {
            "defaultSpringLength": 220,
            "defaultSpringCoefficient": 8e-6,
            "defaultNodeMass": 6,
            "defaultEdgeWeight": 0.45,
        }

        p4c.set_layout_properties(
            name,
            {k: v for k, v in chosen_props.items() if k in props},
        )
        p4c.layout_network(name)
        p4c.fit_content()
        return name

    for fallback in ["cose", "degree-circle", "attribute-circle", "grid"]:
        if fallback in layouts:
            p4c.layout_network(layouts[fallback])
            p4c.fit_content()
            return layouts[fallback]

    p4c.fit_content()
    return None


def create_style() -> None:
    if STYLE_NAME in p4c.get_visual_style_names():
        p4c.delete_visual_style(STYLE_NAME)

    defaults = {
        "NODE_FILL_COLOR": "#dcdcdc",
        "NODE_BORDER_WIDTH": 1.2,
        "NODE_BORDER_PAINT": "#777777",
        "NODE_SIZE": 38,
        "NODE_LABEL_FONT_SIZE": 12,
        "NODE_LABEL_COLOR": "#111111",
        "EDGE_WIDTH": 1.6,
        "EDGE_STROKE_UNSELECTED_PAINT": "#888888",
        "EDGE_TARGET_ARROW_SHAPE": "DELTA",
        "EDGE_TARGET_ARROW_UNSELECTED_PAINT": "#888888",
        "NETWORK_BACKGROUND_PAINT": "#ffffff",
    }

    p4c.create_visual_style(STYLE_NAME, defaults=defaults)
    p4c.set_visual_style(STYLE_NAME)

    p4c.set_node_label_mapping("label", style_name=STYLE_NAME)

    # ---- Nodes ----
    p4c.set_node_color_mapping(
        "node_type",
        ["graph", "scc", "selected"],
        [
            "#dcdcdc",   # visible gray
            "#ffd43b",   # strong yellow
            "#f4a3a3",   # red-ish
        ],
        mapping_type="d",
        style_name=STYLE_NAME,
    )

    p4c.set_node_border_color_mapping(
        "node_type",
        ["graph", "scc", "selected"],
        [
            "#888888",
            "#c49a00",
            "#b00000",
        ],
        mapping_type="d",
        style_name=STYLE_NAME,
    )

    p4c.set_node_border_width_mapping(
        "node_type",
        ["graph", "scc", "selected"],
        [1.2, 3.0, 4.2],
        mapping_type="d",
        style_name=STYLE_NAME,
    )

    p4c.set_node_size_mapping(
        "node_type",
        ["graph", "scc", "selected"],
        [36, 56, 66],
        mapping_type="d",
        style_name=STYLE_NAME,
    )

    # ---- Edges ----
    p4c.set_edge_color_mapping(
        "edge_type",
        ["graph", "scc", "selected"],
        [
            "#aaaaaa",   # lighter but still visible
            "#ffd000",   # bright yellow
            "#d62728",
        ],
        mapping_type="d",
        style_name=STYLE_NAME,
    )

    p4c.set_edge_target_arrow_color_mapping(
        "edge_type",
        ["graph", "scc", "selected"],
        [
            "#aaaaaa",
            "#ffd000",
            "#d62728",
        ],
        mapping_type="d",
        style_name=STYLE_NAME,
    )

    p4c.set_edge_line_width_mapping(
        "edge_type",
        ["graph", "scc", "selected"],
        [
            1.4,   # visible but secondary
            6.0,   # SCC strong
            6.0,   # selected strong
        ],
        mapping_type="d",
        style_name=STYLE_NAME,
    )

    p4c.set_visual_style(STYLE_NAME)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_root")
    parser.add_argument("repo")
    parser.add_argument("branch")
    parser.add_argument("cycles_to_analyze")
    parser.add_argument("--export")
    args = parser.parse_args()

    ensure_cytoscape_running()

    atd = Path(args.results_root) / args.repo / "branches" / args.branch / "ATD_identification"

    dep = load_json(atd / "dependency_graph.json")
    scc_report = load_json(atd / "scc_report.json")
    catalog = load_json(atd / "cycle_catalog.json")

    selected_ids = load_selected_cycles(Path(args.cycles_to_analyze), args.repo, args.branch)

    all_edges = {(e["source"], e["target"]) for e in dep["edges"]}

    scc_nodes: Set[str] = set()
    scc_edges: Set[Tuple[str, str]] = set()

    for scc in scc_report.get("sccs", []):
        scc_nodes.update(n["id"] for n in scc.get("nodes", []))
        scc_edges.update((e["source"], e["target"]) for e in scc.get("edges", []))

    selected_nodes: Set[str] = set()
    selected_edges: Set[Tuple[str, str]] = set()

    for scc in catalog.get("sccs", []):
        for cycle in scc.get("cycles", []):
            if cycle.get("id") in selected_ids:
                selected_nodes.update(cycle.get("nodes", []))
                selected_edges.update(edges_from_cycle(cycle))

    nodes = []
    for n in dep["nodes"]:
        nid = n["id"]

        if nid in selected_nodes:
            node_type = "selected"
            label = short_label(nid)
        elif nid in scc_nodes:
            node_type = "scc"
            label = short_label(nid)
        else:
            node_type = "graph"
            label = ""

        nodes.append({"id": nid, "label": label, "node_type": node_type})

    nodes_df = pd.DataFrame(nodes)

    edge_rows = []
    for u, v in sorted(all_edges):
        if (u, v) in selected_edges:
            edge_type = "selected"
        elif (u, v) in scc_edges:
            edge_type = "scc"
        else:
            edge_type = "graph"

        edge_rows.append(
            {
                "source": u,
                "target": v,
                "interaction": "dep",
                "edge_type": edge_type,
                "name": f"{u} -> {v}",
            }
        )

    edges_df = pd.DataFrame(edge_rows)

    p4c.delete_all_networks()

    p4c.create_network_from_data_frames(
        nodes=nodes_df,
        edges=edges_df,
        title=f"{args.repo}@{args.branch}: SCCs and selected cycles",
        collection="Cycle Analysis",
    )

    create_style()
    apply_layout()

    if args.export:
        p4c.export_image(args.export, type="PNG", overwrite_file=True)

    print("Done.")


if __name__ == "__main__":
    main()