# table_makers/figures/make_difficulty_plots.py
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import matplotlib.pyplot as plt
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


def _extract_scc_record(scc_report: Dict[str, Any], scc_id: str) -> Optional[Dict[str, Any]]:
    sccs = scc_report.get("sccs", [])
    if not isinstance(sccs, list):
        return None

    for scc in sccs:
        if isinstance(scc, dict) and scc.get("id") == scc_id:
            return scc

    return None


def _extract_scc_nodes(scc_record: Dict[str, Any]) -> Set[str]:
    nodes_raw = scc_record.get("nodes", [])
    out: Set[str] = set()

    if not isinstance(nodes_raw, list):
        return out

    for node in nodes_raw:
        if isinstance(node, str):
            out.add(node)
        elif isinstance(node, dict) and isinstance(node.get("id"), str):
            out.add(node["id"])

    return out


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


def _empty_difficulty_metrics() -> Dict[str, Optional[int]]:
    return {
        "baseline_scc_size": None,
        "baseline_scc_edge_count": None,
        "baseline_scc_redundancy": None,
        "baseline_scc_in_edges": None,
        "baseline_scc_out_edges": None,
        "baseline_scc_external_edges": None,
    }


def _baseline_difficulty_for_row(row: pd.Series) -> Dict[str, Optional[int]]:
    cycle_id = str(row.get("cycle_id", ""))
    scc_id = _parse_baseline_scc_id(cycle_id)

    if scc_id is None:
        return _empty_difficulty_metrics()

    scc_report_path = Path(str(row.get("baseline_scc_report_path", "")))
    graph_path = Path(str(row.get("baseline_graph_path", "")))

    scc_report = _read_json(scc_report_path)
    if scc_report is None:
        return _empty_difficulty_metrics()

    scc_record = _extract_scc_record(scc_report, scc_id)
    if scc_record is None:
        return _empty_difficulty_metrics()

    nodes = _extract_scc_nodes(scc_record)

    size = int(scc_record.get("size", len(nodes)) or 0)
    edge_count = int(scc_record.get("edge_count", 0) or 0)
    redundancy = max(0, edge_count - size)

    edges = _parse_graph_edges(graph_path)
    in_edges = sum(1 for src, dst in edges if src not in nodes and dst in nodes)
    out_edges = sum(1 for src, dst in edges if src in nodes and dst not in nodes)

    return {
        "baseline_scc_size": size,
        "baseline_scc_edge_count": edge_count,
        "baseline_scc_redundancy": redundancy,
        "baseline_scc_in_edges": in_edges,
        "baseline_scc_out_edges": out_edges,
        "baseline_scc_external_edges": in_edges + out_edges,
    }


def build_cycle_level_difficulty_df(all_runs_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(all_runs_csv)

    if df.empty:
        return pd.DataFrame()

    difficulty_rows = []
    key_cols = ["repo", "cycle_id", "baseline_scc_report_path", "baseline_graph_path"]

    for _, row in df[key_cols].drop_duplicates().iterrows():
        metrics = _baseline_difficulty_for_row(row)
        difficulty_rows.append(
            {
                "repo": row["repo"],
                "cycle_id": row["cycle_id"],
                **metrics,
            }
        )

    difficulty_df = pd.DataFrame(difficulty_rows)

    group_cols = [
        "mode_id",
        "mode_label",
        "repo",
        "cycle_id",
        "language",
    ]

    if "cycle_size" in df.columns:
        group_cols.append("cycle_size")

    outcome_df = (
        df.groupby(group_cols, dropna=False)
        .agg(
            runs=("success", "size"),
            success_rate=("success", "mean"),
            behavior_preserved_rate=("behavior_preserved", "mean"),
            cycle_broken_rate=("cycle_broken", "mean"),
            local_improvement_rate=("local_improvement", "mean"),
        )
        .reset_index()
    )

    out = outcome_df.merge(difficulty_df, on=["repo", "cycle_id"], how="left")

    for col in [
        "success_rate",
        "behavior_preserved_rate",
        "cycle_broken_rate",
        "local_improvement_rate",
    ]:
        out[col] = out[col] * 100.0

    return out


def _safe_filename(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "plot"


def _save(fig: plt.Figure, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def _scatter_two_metrics(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    x_label: str,
    y_label: str,
    out_path: Path,
    title: str,
    log_x: bool = False,
    log_y: bool = False,
) -> None:
    plot_df = df.dropna(subset=[x_col, y_col, "success_rate"]).copy()

    if log_x:
        plot_df = plot_df[plot_df[x_col] > 0].copy()
    if log_y:
        plot_df = plot_df[plot_df[y_col] > 0].copy()

    if plot_df.empty:
        return

    fig, ax = plt.subplots(figsize=(7.0, 4.8))

    scatter = ax.scatter(
        plot_df[x_col],
        plot_df[y_col],
        c=plot_df["success_rate"],
        s=70,
        alpha=0.8,
        edgecolors="black",
        linewidths=0.35,
    )

    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)

    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")

    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Cycle-level success rate (%)")

    _save(fig, out_path)


def _write_plots_for_df(df: pd.DataFrame, *, outdir: Path, prefix: str, title_suffix: str) -> None:
    _scatter_two_metrics(
        df,
        x_col="baseline_scc_size",
        y_col="baseline_scc_redundancy",
        x_label="Baseline witness SCC size (nodes)",
        y_label="Baseline witness SCC redundancy (edges - nodes)",
        out_path=outdir / f"{prefix}_scc_size_vs_redundancy.png",
        title=f"SCC size and redundancy: {title_suffix}",
        log_x=True,
        log_y=True,
    )

    _scatter_two_metrics(
        df,
        x_col="baseline_scc_in_edges",
        y_col="baseline_scc_out_edges",
        x_label="Incoming edges to baseline witness SCC",
        y_label="Outgoing edges from baseline witness SCC",
        out_path=outdir / f"{prefix}_incoming_vs_outgoing_edges.png",
        title=f"SCC external connectivity: {title_suffix}",
        log_x=False,
        log_y=False,
    )

    if "cycle_size" in df.columns:
        _scatter_two_metrics(
            df,
            x_col="cycle_size",
            y_col="baseline_scc_size",
            x_label="Sampled cycle size (files)",
            y_label="Baseline witness SCC size (nodes)",
            out_path=outdir / f"{prefix}_cycle_size_vs_scc_size.png",
            title=f"Cycle size and SCC size: {title_suffix}",
            log_x=False,
            log_y=True,
        )

        _scatter_two_metrics(
            df,
            x_col="cycle_size",
            y_col="baseline_scc_redundancy",
            x_label="Sampled cycle size (files)",
            y_label="Baseline witness SCC redundancy (edges - nodes)",
            out_path=outdir / f"{prefix}_cycle_size_vs_scc_redundancy.png",
            title=f"Cycle size and SCC redundancy: {title_suffix}",
            log_x=False,
            log_y=True,
        )


def write_difficulty_scatter_plots(
    all_runs_csv: Path,
    outdir: Path,
    *,
    write_cycle_level_csv: bool = True,
) -> None:
    cycle_df = build_cycle_level_difficulty_df(all_runs_csv)
    outdir.mkdir(parents=True, exist_ok=True)

    if write_cycle_level_csv:
        cycle_df.to_csv(outdir / "cycle_level_difficulty.csv", index=False)

    if cycle_df.empty:
        return

    _write_plots_for_df(
        cycle_df,
        outdir=outdir,
        prefix="all_modes",
        title_suffix="all configurations",
    )

    for mode_id, mode_df in cycle_df.groupby("mode_id", dropna=False):
        mode_label = (
            str(mode_df["mode_label"].dropna().iloc[0])
            if not mode_df["mode_label"].dropna().empty
            else str(mode_id)
        )

        _write_plots_for_df(
            mode_df,
            outdir=outdir,
            prefix=_safe_filename(str(mode_id)),
            title_suffix=mode_label,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all-runs",
        required=True,
        help="Path to derived/all_runs.csv",
    )
    parser.add_argument(
        "--outdir",
        required=True,
        help="Directory where figures and cycle-level CSV should be written",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    write_difficulty_scatter_plots(
        all_runs_csv=Path(args.all_runs).resolve(),
        outdir=Path(args.outdir).resolve(),
    )


if __name__ == "__main__":
    main()