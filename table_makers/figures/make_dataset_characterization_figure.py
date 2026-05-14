#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE_MAKERS_DIR = REPO_ROOT / "table_makers"

for path in [REPO_ROOT, TABLE_MAKERS_DIR]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from table_makers.core.dataset_builder import build_all_runs_dataframe
from table_makers.metrics.metrics_difficulty import add_difficulty_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dev", required=True)
    parser.add_argument("--analysis-plan-dev", required=True)
    parser.add_argument("--config-eval", required=True)
    parser.add_argument("--analysis-plan-eval", required=True)
    parser.add_argument("--outdir", required=True)
    return parser.parse_args()


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
                "cycle_size",
                "cycle_centrality",
                "baseline_scc_size",
                "repo_dependency_graph_size",
                "cycle_external_edges",
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
        "repo_dependency_graph_size",
        "cycle_external_edges",
    ]:
        cycles[col] = pd.to_numeric(cycles[col], errors="coerce")

    return cycles


def get_palette() -> dict[str, str]:
    return {
        "Development": "#4C72B0",
        "Evaluation": "#C44E52",
    }


def draw_cycle_size(ax, cycles: pd.DataFrame, palette: dict[str, str]) -> None:
    sizes = list(range(2, 9))

    df = cycles[["split", "cycle_size"]].dropna().copy()
    df["cycle_size"] = df["cycle_size"].astype(int)

    counts = (
        df.groupby(["split", "cycle_size"])
        .size()
        .reset_index(name="Selected cycles")
    )

    sns.barplot(
        data=counts,
        x="cycle_size",
        y="Selected cycles",
        hue="split",
        hue_order=["Development", "Evaluation"],
        palette=palette,
        saturation=1.0,
        order=sizes,
        edgecolor="black",
        linewidth=0.5,
        ax=ax,
    )

    ax.set_title("Cycle size distribution", weight="bold", fontsize=11)
    ax.set_xlabel("Cycle length (files)", fontsize=10)
    ax.set_ylabel("Selected cycles", fontsize=10)

    ax.tick_params(axis="both", labelsize=9.5)
    ax.grid(axis="y", linestyle=":", linewidth=0.6)

    ax.legend(
        frameon=False,
        title=None,
        fontsize=9.5,
        handlelength=1.3,
        handletextpad=0.45,
        borderaxespad=0.2,
    )

    sns.despine(ax=ax)


def bounded_jitter(
    center: float,
    n: int,
    *,
    width: float,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return center + rng.uniform(-width, width, size=n)


def draw_jitter_with_iqr(
    ax,
    cycles: pd.DataFrame,
    column: str,
    title: str,
    ylabel: str,
    palette: dict[str, str],
) -> None:
    df = cycles[["split", column]].dropna().copy()

    groups = [
        ("Development", 0.0, 11),
        ("Evaluation", 0.55, 22),
    ]

    jitter_width = 0.12
    point_size = 30
    point_alpha = 0.42

    for split, x, seed in groups:
        values = df[df["split"] == split][column].dropna()

        ax.scatter(
            bounded_jitter(x, len(values), width=jitter_width, seed=seed),
            values,
            facecolors=palette[split],
            edgecolors="black",
            linewidths=0.22,
            alpha=point_alpha,
            s=point_size,
            zorder=3,
        )

        if len(values):
            q1 = values.quantile(0.25)
            median = values.median()
            q3 = values.quantile(0.75)

            ax.vlines(
                x,
                q1,
                q3,
                color="black",
                linewidth=1.25,
                alpha=0.98,
                zorder=4,
            )

            ax.hlines(
                [q1, q3],
                x - 0.06,
                x + 0.06,
                color="black",
                linewidth=1.25,
                alpha=0.98,
                zorder=4,
            )

            ax.hlines(
                median,
                x - 0.15,
                x + 0.15,
                color="black",
                linewidth=2.0,
                zorder=5,
            )

    ax.set_xlim(-0.24, 0.79)
    ax.set_xticks([0.0, 0.55])
    ax.set_xticklabels(["Development", "Evaluation"], fontsize=9.2)

    ax.yaxis.set_major_locator(plt.MaxNLocator(5))

    ax.set_title(title, weight="bold", fontsize=10.5)
    ax.set_xlabel("")
    ax.set_ylabel(ylabel, fontsize=9.5)

    ax.tick_params(axis="y", labelsize=9.2)
    ax.tick_params(axis="x", labelsize=9.2)

    ax.grid(axis="y", linestyle=":", linewidth=0.6, zorder=0)

    sns.despine(ax=ax)


def _format_number(value: float | int | None, *, decimals: int) -> str:
    if value is None or pd.isna(value):
        return ""

    value = float(value)

    if decimals == 0:
        return f"{int(round(value)):,}"

    return f"{value:.{decimals}f}"


def _summarize_property(
    cycles: pd.DataFrame,
    *,
    property_label: str,
    column: str,
    decimals: int,
    split_order: Iterable[str] = ("Development", "Evaluation"),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for split in split_order:
        values = cycles.loc[cycles["split"] == split, column].dropna()

        if values.empty:
            rows.append(
                {
                    "Property": property_label,
                    "Split": "Dev" if split == "Development" else "Eval",
                    "Cycles": 0,
                    "Median": "",
                    "IQR": "",
                    "Range": "",
                    "Q1_raw": "",
                    "Median_raw": "",
                    "Q3_raw": "",
                    "Min_raw": "",
                    "Max_raw": "",
                }
            )
            continue

        q1 = float(values.quantile(0.25))
        median = float(values.median())
        q3 = float(values.quantile(0.75))
        min_value = float(values.min())
        max_value = float(values.max())

        rows.append(
            {
                "Property": property_label,
                "Split": "Dev" if split == "Development" else "Eval",
                "Cycles": int(len(values)),
                "Median": _format_number(median, decimals=decimals),
                "IQR": (
                    f"{_format_number(q1, decimals=decimals)}--"
                    f"{_format_number(q3, decimals=decimals)}"
                ),
                "Range": (
                    f"{_format_number(min_value, decimals=decimals)}--"
                    f"{_format_number(max_value, decimals=decimals)}"
                ),
                "Q1_raw": q1,
                "Median_raw": median,
                "Q3_raw": q3,
                "Min_raw": min_value,
                "Max_raw": max_value,
            }
        )

    return rows


def build_dataset_characterization_summary(cycles: pd.DataFrame) -> pd.DataFrame:
    specs = [
        {
            "property_label": "Cycle centrality",
            "column": "cycle_centrality",
            "decimals": 2,
        },
        {
            "property_label": "Enclosing SCC size",
            "column": "baseline_scc_size",
            "decimals": 0,
        },
        {
            "property_label": "Repository size",
            "column": "repo_dependency_graph_size",
            "decimals": 0,
        },
        {
            "property_label": "Cycle external connectivity",
            "column": "cycle_external_edges",
            "decimals": 0,
        },
    ]

    rows: list[dict[str, object]] = []
    for spec in specs:
        rows.extend(_summarize_property(cycles, **spec))

    return pd.DataFrame(
        rows,
        columns=[
            "Property",
            "Split",
            "Cycles",
            "Median",
            "IQR",
            "Range",
            "Q1_raw",
            "Median_raw",
            "Q3_raw",
            "Min_raw",
            "Max_raw",
        ],
    )


def build_cycle_size_counts(cycles: pd.DataFrame) -> pd.DataFrame:
    df = cycles[["split", "cycle_size"]].dropna().copy()
    df["cycle_size"] = df["cycle_size"].astype(int)

    counts = (
        df.groupby(["split", "cycle_size"])
        .size()
        .reset_index(name="Selected cycles")
    )

    split_order = ["Development", "Evaluation"]
    sizes = list(range(2, 9))
    full_index = pd.MultiIndex.from_product(
        [split_order, sizes],
        names=["split", "cycle_size"],
    )

    counts = (
        counts.set_index(["split", "cycle_size"])
        .reindex(full_index, fill_value=0)
        .reset_index()
    )

    return counts


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    sns.set_theme(
        context="paper",
        style="ticks",
        font_scale=0.9,
        rc={
            "axes.facecolor": "white",
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "grid.color": "0.82",
        },
    )

    palette = get_palette()

    dev = load_cycles(Path(args.config_dev), Path(args.analysis_plan_dev), "Development")
    eval_ = load_cycles(Path(args.config_eval), Path(args.analysis_plan_eval), "Evaluation")

    cycles = pd.concat([dev, eval_], ignore_index=True)

    raw_characterization_path = outdir / "dataset_cycle_characterization.csv"
    summary_path = outdir / "dataset_characterization_summary.csv"
    cycle_size_counts_path = outdir / "cycle_size_counts.csv"

    cycles.to_csv(raw_characterization_path, index=False)
    build_dataset_characterization_summary(cycles).to_csv(summary_path, index=False)
    build_cycle_size_counts(cycles).to_csv(cycle_size_counts_path, index=False)

    # Smaller canvas plus slightly larger internal fonts.
    # This makes text look larger when included in LaTeX at the same width.
    fig1, ax1 = plt.subplots(figsize=(4.35, 3.05))
    draw_cycle_size(ax1, cycles, palette)
    fig1.tight_layout(pad=0.35)

    cycle_size_path = outdir / "cycle_size_distribution.png"
    fig1.savefig(cycle_size_path, dpi=300, bbox_inches="tight")
    plt.close(fig1)

    # Same trick for the jitter panels. The canvas is smaller than before,
    # while fonts are explicitly set in draw_jitter_with_iqr.
    fig2, axes = plt.subplots(2, 2, figsize=(5.85, 5.25))
    axes = axes.flatten()

    draw_jitter_with_iqr(
        axes[0],
        cycles,
        "cycle_centrality",
        "Cycle centrality",
        "Relative PageRank",
        palette,
    )
    draw_jitter_with_iqr(
        axes[1],
        cycles,
        "baseline_scc_size",
        "Enclosing SCC size",
        "Files in SCC",
        palette,
    )
    draw_jitter_with_iqr(
        axes[2],
        cycles,
        "repo_dependency_graph_size",
        "Repository size",
        "Files in dependency graph",
        palette,
    )
    draw_jitter_with_iqr(
        axes[3],
        cycles,
        "cycle_external_edges",
        "External connectivity",
        "Cross-boundary edges",
        palette,
    )

    fig2.tight_layout(pad=0.55, w_pad=1.0, h_pad=1.0)

    difficulty_path = outdir / "cycle_difficulty_jitter_iqr.png"
    fig2.savefig(difficulty_path, dpi=300, bbox_inches="tight")
    plt.close(fig2)

    print(f"Wrote {raw_characterization_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {cycle_size_counts_path}")
    print(f"Wrote {cycle_size_path}")
    print(f"Wrote {difficulty_path}")


if __name__ == "__main__":
    main()