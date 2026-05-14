# table_makers/tables/make_global_regression_criteria.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


GLOBAL_REGRESSION_CRITERIA_COLUMNS = [
    "mode_id",
    "Configuration",
    "Denominator",
    "Any global regression",
    "Redundancy increase",
    "New outside-target cyclic nodes",
    "Both criteria",
]


def build_global_regression_criteria_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(columns=GLOBAL_REGRESSION_CRITERIA_COLUMNS)

    required = [
        "mode_id",
        "mode_label",
        "structurally_evaluable",
        "behavior_preserved",
        "baseline_global_redundancy",
        "post_global_redundancy",
        "global_structural_regression_raw",
        "global_regression_outside_target_raw",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build global-regression criteria table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id].copy()

        # Same denominator as the old local/global spillover table:
        # structurally evaluable runs that preserve behavior.
        denom_df = mode_df[
            (mode_df["structurally_evaluable"] == 1)
            & (mode_df["behavior_preserved"] == 1)
        ].copy()

        denom = int(len(denom_df))

        if denom:
            redundancy_increase = (
                denom_df["post_global_redundancy"].astype(int)
                > denom_df["baseline_global_redundancy"].astype(int)
            )

            outside_target = (
                denom_df["global_regression_outside_target_raw"].astype(int) == 1
            )

            any_global_regression = (
                denom_df["global_structural_regression_raw"].astype(int) == 1
            )

            both_criteria = redundancy_increase & outside_target

            redundancy_increase_n = int(redundancy_increase.sum())
            outside_target_n = int(outside_target.sum())
            any_global_regression_n = int(any_global_regression.sum())
            both_criteria_n = int(both_criteria.sum())
        else:
            redundancy_increase_n = 0
            outside_target_n = 0
            any_global_regression_n = 0
            both_criteria_n = 0

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Denominator": denom,
                "Any global regression": pct(any_global_regression_n, denom),
                "Redundancy increase": pct(redundancy_increase_n, denom),
                "New outside-target cyclic nodes": pct(outside_target_n, denom),
                "Both criteria": pct(both_criteria_n, denom),
            }
        )

    return pd.DataFrame(rows, columns=GLOBAL_REGRESSION_CRITERIA_COLUMNS)


def write_global_regression_criteria_csv(
    all_runs_csv_path: Path,
    outdir: Path,
) -> Path:
    df = build_global_regression_criteria_rows(all_runs_csv_path)
    out_path = outdir / "global_regression_criteria.csv"
    write_dataframe_csv(out_path, df)
    return out_path