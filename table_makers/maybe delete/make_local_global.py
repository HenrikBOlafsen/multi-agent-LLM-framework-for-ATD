from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


def build_local_global_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "mode_id",
                "Configuration",
                "Local improvement",
                "Any global regression",
                "Global regression outside target SCC",
            ]
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id]

        denom_df = mode_df[
            (mode_df["structurally_evaluable"] == 1)
            & (mode_df["behavior_preserved"] == 1)
        ]
        denom = int(len(denom_df))

        local_improvement_n = int(denom_df["local_improvement"].sum()) if denom else 0
        any_global_regression_n = int(denom_df["global_structural_regression_raw"].sum()) if denom else 0
        outside_target_n = (
            int(
                (
                    (denom_df["global_structural_regression_raw"] == 1)
                    & (denom_df["global_regression_outside_target_raw"] == 1)
                ).sum()
            )
            if denom
            else 0
        )

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Local improvement": pct(local_improvement_n, denom),
                "Any global regression": pct(any_global_regression_n, denom),
                "Global regression outside target SCC": pct(outside_target_n, denom),
            }
        )

    return pd.DataFrame(rows)


def write_local_global_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_local_global_rows(all_runs_csv_path)
    out_path = outdir / "local_global.csv"
    write_dataframe_csv(out_path, df)
    return out_path