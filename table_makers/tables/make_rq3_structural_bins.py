from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import load_all_runs_df
from metrics.metrics_difficulty import (
    add_difficulty_metrics,
    bin_cycle_centrality,
    bin_cycle_external_edges,
    bin_fixed_scc_size,
    bin_repo_size,
    sort_bin_label,
)


STRUCTURAL_BIN_COLUMNS = [
    "Factor",
    "Bin",
    "Cycles",
    "Runs per configuration",
    "Baseline successes",
    "Baseline success (%)",
    "Selected successes",
    "Selected success (%)",
]


def _selected_mode_id(mode_ids: list[str]) -> Optional[str]:
    non_baseline = [mode_id for mode_id in mode_ids if mode_id != "no_explain"]
    if "no_explain" not in mode_ids or len(non_baseline) != 1:
        return None
    return non_baseline[0]


def _success_pct(successes: int, runs: int) -> Optional[float]:
    return pct(successes, runs)


def _build_factor_rows(
    df: pd.DataFrame,
    *,
    factor_name: str,
    raw_column: str,
    bin_column: str,
    bin_function: Callable[[object], Optional[str]],
    selected_mode: str,
) -> list[dict[str, object]]:
    work = df[
        [
            "repo",
            "cycle_id",
            "mode_id",
            "success",
            raw_column,
        ]
    ].copy()

    work[bin_column] = work[raw_column].apply(bin_function)
    work = work[work[bin_column].notna()].copy()

    rows: list[dict[str, object]] = []

    for bin_label in sorted(
        work[bin_column].dropna().unique(),
        key=sort_bin_label,
    ):
        bin_df = work[work[bin_column] == bin_label].copy()

        cycles = (
            bin_df[["repo", "cycle_id"]]
            .drop_duplicates()
            .shape[0]
        )

        baseline_df = bin_df[bin_df["mode_id"] == "no_explain"]
        selected_df = bin_df[bin_df["mode_id"] == selected_mode]

        baseline_runs = int(len(baseline_df))
        selected_runs = int(len(selected_df))

        if baseline_runs != selected_runs:
            runs_per_configuration: object = f"{baseline_runs}/{selected_runs}"
        else:
            runs_per_configuration = baseline_runs

        baseline_successes = int(baseline_df["success"].sum())
        selected_successes = int(selected_df["success"].sum())

        rows.append(
            {
                "Factor": factor_name,
                "Bin": bin_label,
                "Cycles": cycles,
                "Runs per configuration": runs_per_configuration,
                "Baseline successes": baseline_successes,
                "Baseline success (%)": _success_pct(
                    baseline_successes,
                    baseline_runs,
                ),
                "Selected successes": selected_successes,
                "Selected success (%)": _success_pct(
                    selected_successes,
                    selected_runs,
                ),
            }
        )

    return rows


def build_rq3_structural_bins_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = add_difficulty_metrics(load_all_runs_df(all_runs_csv_path))

    if df.empty:
        return pd.DataFrame(columns=STRUCTURAL_BIN_COLUMNS)

    required = [
        "repo",
        "cycle_id",
        "mode_id",
        "success",
        "cycle_centrality",
        "baseline_scc_size",
        "repo_dependency_graph_size",
        "cycle_external_edges",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build RQ3 structural-bin table because all_runs.csv is missing columns: "
            + ", ".join(missing)
        )

    mode_ids = list(df["mode_id"].dropna().astype(str).drop_duplicates())
    selected_mode = _selected_mode_id(mode_ids)

    if selected_mode is None:
        return pd.DataFrame(columns=STRUCTURAL_BIN_COLUMNS)

    df = df.copy()
    df["success"] = pd.to_numeric(df["success"], errors="coerce").fillna(0).astype(int)

    rows: List[Dict[str, object]] = []

    rows.extend(
        _build_factor_rows(
            df,
            factor_name="Cycle centrality",
            raw_column="cycle_centrality",
            bin_column="cycle_centrality_bin",
            bin_function=bin_cycle_centrality,
            selected_mode=selected_mode,
        )
    )

    rows.extend(
        _build_factor_rows(
            df,
            factor_name="Enclosing SCC size",
            raw_column="baseline_scc_size",
            bin_column="scc_size_bin",
            bin_function=bin_fixed_scc_size,
            selected_mode=selected_mode,
        )
    )

    rows.extend(
        _build_factor_rows(
            df,
            factor_name="Repository size",
            raw_column="repo_dependency_graph_size",
            bin_column="repo_size_bin",
            bin_function=bin_repo_size,
            selected_mode=selected_mode,
        )
    )

    rows.extend(
        _build_factor_rows(
            df,
            factor_name="Cycle external connectivity",
            raw_column="cycle_external_edges",
            bin_column="cycle_external_bin",
            bin_function=bin_cycle_external_edges,
            selected_mode=selected_mode,
        )
    )

    return pd.DataFrame(rows, columns=STRUCTURAL_BIN_COLUMNS)


def write_rq3_structural_bins_csv(
    all_runs_csv_path: Path,
    outdir: Path,
) -> Path:
    df = build_rq3_structural_bins_rows(all_runs_csv_path)
    out_path = outdir / "eval_rq3_structural_bins.csv"
    write_dataframe_csv(out_path, df)
    return out_path