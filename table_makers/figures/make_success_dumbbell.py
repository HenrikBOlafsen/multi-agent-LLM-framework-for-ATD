#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


NO_EXPLANATION_COLOR = "#4C72B0"
DESCRIPTIVE_COLOR = "#55A868"
ADVISORY_COLOR = "#C44E52"
DIRECTIVE_COLOR = "#8172B2"
CONNECTOR_COLOR = "0.68"


MODE_STYLES: dict[str, dict[str, Any]] = {
    "no_explain": {
        "label": "No-explanation",
        "color": NO_EXPLANATION_COLOR,
        "marker": "o",
        "size": 48,
        "zorder": 8,
    },
    "explain_E0_S0_noaux": {
        "label": "Descriptive",
        "color": DESCRIPTIVE_COLOR,
        "marker": "s",
        "size": 44,
        "zorder": 4,
    },
    "explain_E1_S1_noaux": {
        "label": "Advisory",
        "color": ADVISORY_COLOR,
        "marker": "D",
        "size": 48,
        "zorder": 5,
    },
    "explain_E2_S2_noaux": {
        "label": "Directive",
        "color": DIRECTIVE_COLOR,
        "marker": "^",
        "size": 52,
        "zorder": 6,
    },
}


def _parse_pct(value: object) -> float:
    if pd.isna(value):
        return float("nan")

    text = str(value).strip().replace("%", "")
    if not text:
        return float("nan")

    return float(text)


def _normalize_language(value: object) -> str:
    text = str(value).strip().lower()

    if text == "python":
        return "Python"

    if text in {"csharp", "c#", "cs", "dotnet", ".net"}:
        return "C#"

    return str(value).strip()


def _fallback_mode_label(mode_id: str) -> str:
    cleaned = (
        mode_id.replace("explain_", "")
        .replace("_noaux", "")
        .replace("_", " ")
        .strip()
    )
    return cleaned or mode_id


def _mode_label(mode_id: str) -> str:
    return MODE_STYLES.get(mode_id, {}).get("label", _fallback_mode_label(mode_id))


def _mode_order(mode_ids: list[str]) -> list[str]:
    preferred = [
        "no_explain",
        "explain_E0_S0_noaux",
        "explain_E1_S1_noaux",
        "explain_E2_S2_noaux",
    ]

    ordered = [m for m in preferred if m in mode_ids]
    ordered.extend([m for m in mode_ids if m not in ordered])

    return ordered


def _read_language_success(language_csv: Path, mode_order: list[str]) -> list[dict[str, object]]:
    df = pd.read_csv(language_csv).copy()
    df["success_pct"] = df["Success"].apply(_parse_pct)
    df["language_norm"] = df["language"].apply(_normalize_language)

    rows: list[dict[str, object]] = []

    for language in ["Python", "C#"]:
        row: dict[str, object] = {
            "group": "Programming language",
            "label": language,
        }

        for mode_id in mode_order:
            match = df[
                (df["language_norm"] == language)
                & (df["mode_id"] == mode_id)
            ]

            row[mode_id] = (
                float(match["success_pct"].iloc[0])
                if not match.empty
                else float("nan")
            )

        rows.append(row)

    return rows


def _read_cycle_size_success(cycle_size_csv: Path, mode_order: list[str]) -> list[dict[str, object]]:
    df = pd.read_csv(cycle_size_csv).copy()
    df["success_pct"] = df["Success"].apply(_parse_pct)

    rows: list[dict[str, object]] = []

    for cycle_bin in ["2--3", "4--6", "7--8"]:
        row: dict[str, object] = {
            "group": "Cycle-size bin",
            "label": cycle_bin,
        }

        for mode_id in mode_order:
            match = df[
                (df["cycle_size_bin"] == cycle_bin)
                & (df["mode_id"] == mode_id)
            ]

            row[mode_id] = (
                float(match["success_pct"].iloc[0])
                if not match.empty
                else float("nan")
            )

        rows.append(row)

    return rows


def _compute_y_offsets(
    row: pd.Series,
    mode_order: list[str],
    tolerance: float = 0.05,
) -> dict[str, float]:
    """
    Offset markers when two or more modes have the same success rate in one row.
    Non-overlapping points stay centered on the row.
    """
    values: list[tuple[str, float]] = []

    for mode_id in mode_order:
        value = row.get(mode_id, float("nan"))
        if pd.notna(value):
            values.append((mode_id, float(value)))

    offsets = {mode_id: 0.0 for mode_id, _ in values}
    assigned: set[str] = set()

    for i, (mode_a, value_a) in enumerate(values):
        if mode_a in assigned:
            continue

        overlap_group = [(mode_a, value_a)]

        for mode_b, value_b in values[i + 1:]:
            if mode_b in assigned:
                continue
            if abs(value_a - value_b) <= tolerance:
                overlap_group.append((mode_b, value_b))

        n = len(overlap_group)

        if n == 2:
            spread = [-0.12, 0.12]
        elif n == 3:
            spread = [-0.16, 0.0, 0.16]
        elif n == 4:
            spread = [-0.21, -0.07, 0.07, 0.21]
        else:
            spread = [0.0]

        for (mode_id, _), offset in zip(overlap_group, spread):
            offsets[mode_id] = offset

        assigned.update(mode for mode, _ in overlap_group)

    return offsets


def make_success_subgroup_dumbbell(
    language_csv: Path,
    cycle_size_csv: Path,
    out_path: Path,
    *,
    title: str,
) -> Path:
    language_df = pd.read_csv(language_csv)
    cycle_size_df = pd.read_csv(cycle_size_csv)

    mode_ids = list(
        dict.fromkeys(
            language_df["mode_id"].dropna().tolist()
            + cycle_size_df["mode_id"].dropna().tolist()
        )
    )
    mode_order = _mode_order(mode_ids)

    rows = (
        _read_language_success(language_csv, mode_order)
        + _read_cycle_size_success(cycle_size_csv, mode_order)
    )

    if not rows:
        raise ValueError("No data found for dumbbell plot.")

    df = pd.DataFrame(rows)

    y_positions = [4.4, 3.4, 1.9, 0.9, -0.1]
    df["y"] = y_positions[: len(df)]

    value_columns = [m for m in mode_order if m in df.columns]
    max_value = max(float(df[m].max()) for m in value_columns if df[m].notna().any())
    x_max = max_value + 4.0

    fig, ax = plt.subplots(figsize=(6.6, 4.15))

    row_offsets: dict[int, dict[str, float]] = {}
    for row_index, row in df.iterrows():
        row_offsets[row_index] = _compute_y_offsets(row, value_columns)

    # Connector lines span the minimum and maximum value within each subgroup.
    for _, row in df.iterrows():
        values = [float(row[m]) for m in value_columns if pd.notna(row[m])]
        if len(values) < 2:
            continue

        ax.plot(
            [min(values), max(values)],
            [row["y"], row["y"]],
            color=CONNECTOR_COLOR,
            linewidth=1.2,
            zorder=1,
        )

    # Draw non-baseline modes first, then No-explanation last.
    # This keeps the circle visible if it overlaps with another marker.
    scatter_order = [m for m in value_columns if m != "no_explain"] + [
        m for m in value_columns if m == "no_explain"
    ]

    handles_by_mode: dict[str, object] = {}

    for mode_id in scatter_order:
        style = MODE_STYLES.get(
            mode_id,
            {
                "label": _fallback_mode_label(mode_id),
                "color": "0.35",
                "marker": "o",
                "size": 44,
                "zorder": 3,
            },
        )

        xs: list[float] = []
        ys: list[float] = []

        for row_index, row in df.iterrows():
            value = row.get(mode_id, float("nan"))
            if pd.isna(value):
                continue

            xs.append(float(value))
            ys.append(float(row["y"]) + row_offsets[row_index].get(mode_id, 0.0))

        if not xs:
            continue

        scatter = ax.scatter(
            xs,
            ys,
            s=style["size"],
            marker=style["marker"],
            color=style["color"],
            edgecolor="black",
            linewidth=0.45,
            label=style["label"],
            zorder=style["zorder"],
        )
        handles_by_mode[mode_id] = scatter

    # Delta labels are useful for the held-out comparison with two configurations,
    # but too cluttered for the development plot with four configurations.
    show_delta_labels = len(value_columns) == 2 and "no_explain" in value_columns
    selected_mode = next((m for m in value_columns if m != "no_explain"), None)

    if show_delta_labels and selected_mode:
        for _, row in df.iterrows():
            baseline = row.get("no_explain", float("nan"))
            selected = row.get(selected_mode, float("nan"))

            if pd.isna(baseline) or pd.isna(selected):
                continue

            delta = float(selected) - float(baseline)
            text_x = max(float(baseline), float(selected)) + 0.45

            ax.text(
                text_x,
                row["y"],
                f"{delta:+.1f} pp",
                va="center",
                ha="left",
                fontsize=8.5,
            )

    ax.set_yticks(df["y"])
    ax.set_yticklabels(df["label"])

    header_x = 0.45
    ax.text(
        header_x,
        4.86,
        "Programming language",
        ha="left",
        va="bottom",
        fontsize=9.5,
        fontweight="bold",
    )
    ax.text(
        header_x,
        2.36,
        "Cycle-size bin",
        ha="left",
        va="bottom",
        fontsize=9.5,
        fontweight="bold",
    )

    ax.axhline(
        2.75,
        color="0.72",
        linewidth=0.9,
        zorder=0,
    )

    ax.set_xlim(0, x_max)
    ax.set_ylim(-0.55, 5.2)

    ax.set_xlabel("Successful refactoring (%)")
    ax.set_title(title, pad=12)

    ax.grid(axis="x", linestyle=":", linewidth=0.8, color="0.80")
    ax.grid(axis="y", visible=False)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.tick_params(axis="y", pad=6)

    # Highlight the final x-axis tick to show that the scale does not run to 100%.
    ticks = ax.get_xticks()
    ticks = [tick for tick in ticks if 0 <= tick <= x_max]
    ax.set_xticks(ticks)

    tick_labels = ax.set_xticklabels([f"{tick:g}" for tick in ticks])
    if tick_labels:
        tick_labels[-1].set_fontweight("bold")
        tick_labels[-1].set_color("0.25")

    legend_order = [m for m in mode_order if m in handles_by_mode]
    handles = [handles_by_mode[m] for m in legend_order]
    labels = [_mode_label(m) for m in legend_order]

    legend = ax.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
        ncol=min(len(handles), 4),
        frameon=True,
        fancybox=False,
        framealpha=0.98,
        borderaxespad=0.0,
    )
    legend.get_frame().set_facecolor("white")
    legend.get_frame().set_edgecolor("0.65")
    legend.get_frame().set_linewidth(0.8)

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.27)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    return out_path


if __name__ == "__main__":
    make_success_subgroup_dumbbell(
        language_csv=Path("analysis_out_eval/language_breakdown.csv"),
        cycle_size_csv=Path("analysis_out_eval/cycle_size_breakdown.csv"),
        out_path=Path("figures/eval_success_language_cycle_size_dumbbell.png"),
        title="Final-evaluation subgroup success rates",
    )

    make_success_subgroup_dumbbell(
        language_csv=Path("analysis_out_dev_paradigm/language_breakdown.csv"),
        cycle_size_csv=Path("analysis_out_dev_paradigm/cycle_size_breakdown.csv"),
        out_path=Path("figures/dev_success_language_cycle_size_dumbbell.png"),
        title="Development-phase subgroup success rates",
    )