#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


NO_EXPLANATION_COLOR = "#4C72B0"
ADVISORY_COLOR = "#C44E52"
CONNECTOR_COLOR = "0.45"


def _parse_pct(value: object) -> float:
    """Parse values like '17.3%' or 17.3 into float percentages."""
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


def _read_language_success(language_csv: Path) -> list[dict[str, object]]:
    df = pd.read_csv(language_csv).copy()
    df["success_pct"] = df["Success"].apply(_parse_pct)
    df["language_norm"] = df["language"].apply(_normalize_language)

    rows: list[dict[str, object]] = []

    for language in ["Python", "C#"]:
        baseline = df[
            (df["language_norm"] == language)
            & (df["mode_id"] == "no_explain")
        ]
        advisory = df[
            (df["language_norm"] == language)
            & (df["mode_id"] != "no_explain")
        ]

        if baseline.empty or advisory.empty:
            continue

        rows.append(
            {
                "group": "Programming language",
                "label": language,
                "no_explanation": float(baseline["success_pct"].iloc[0]),
                "advisory": float(advisory["success_pct"].iloc[0]),
            }
        )

    return rows


def _read_cycle_size_success(cycle_size_csv: Path) -> list[dict[str, object]]:
    df = pd.read_csv(cycle_size_csv).copy()
    df["success_pct"] = df["Success"].apply(_parse_pct)

    rows: list[dict[str, object]] = []

    for cycle_bin in ["2--3", "4--6", "7--8"]:
        baseline = df[
            (df["cycle_size_bin"] == cycle_bin)
            & (df["mode_id"] == "no_explain")
        ]
        advisory = df[
            (df["cycle_size_bin"] == cycle_bin)
            & (df["mode_id"] != "no_explain")
        ]

        if baseline.empty or advisory.empty:
            continue

        rows.append(
            {
                "group": "Cycle-size bin",
                "label": cycle_bin,
                "no_explanation": float(baseline["success_pct"].iloc[0]),
                "advisory": float(advisory["success_pct"].iloc[0]),
            }
        )

    return rows


def make_eval_success_dumbbell(
    language_csv: Path,
    cycle_size_csv: Path,
    out_path: Path,
) -> Path:
    rows = _read_language_success(language_csv) + _read_cycle_size_success(cycle_size_csv)

    if not rows:
        raise ValueError("No data found for dumbbell plot.")

    df = pd.DataFrame(rows)

    y_positions = [4.4, 3.4, 1.9, 0.9, -0.1]
    df["y"] = y_positions[: len(df)]

    max_value = max(df["no_explanation"].max(), df["advisory"].max())
    x_max = max_value + 3.2

    fig, ax = plt.subplots(figsize=(6.6, 4.1))

    for _, row in df.iterrows():
        ax.plot(
            [row["no_explanation"], row["advisory"]],
            [row["y"], row["y"]],
            color=CONNECTOR_COLOR,
            linewidth=1.3,
            zorder=1,
        )

    ax.scatter(
        df["no_explanation"],
        df["y"],
        s=42,
        marker="o",
        color=NO_EXPLANATION_COLOR,
        edgecolor="black",
        linewidth=0.4,
        label="No-explanation",
        zorder=3,
    )

    ax.scatter(
        df["advisory"],
        df["y"],
        s=48,
        marker="D",
        color=ADVISORY_COLOR,
        edgecolor="black",
        linewidth=0.4,
        label="Advisory",
        zorder=4,
    )

    for _, row in df.iterrows():
        delta = row["advisory"] - row["no_explanation"]
        text_x = max(row["no_explanation"], row["advisory"]) + 0.45
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

    header_x = 0.35
    ax.text(
        header_x,
        4.85,
        "Programming language",
        ha="left",
        va="bottom",
        fontsize=9.5,
        fontweight="bold",
    )
    ax.text(
        header_x,
        2.35,
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
    ax.set_title("Final-evaluation subgroup success rates", pad=12)

    ax.grid(axis="x", linestyle=":", linewidth=0.8, color="0.80")
    ax.grid(axis="y", visible=False)

    legend = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.23),
        ncol=2,
        frameon=True,
        fancybox=False,
        framealpha=0.96,
        borderpad=0.45,
        handletextpad=0.6,
        columnspacing=1.2,
    )
    legend.get_frame().set_facecolor("white")
    legend.get_frame().set_edgecolor("0.65")
    legend.get_frame().set_linewidth(0.8)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.tick_params(axis="y", pad=6)

    fig.tight_layout(rect=(0, 0.12, 1, 1))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    return out_path


if __name__ == "__main__":
    make_eval_success_dumbbell(
        language_csv=Path("analysis_out_eval/language_breakdown.csv"),
        cycle_size_csv=Path("analysis_out_eval/cycle_size_breakdown.csv"),
        out_path=Path("figures/eval_success_language_cycle_size_dumbbell.png"),
    )