from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


def build_main_results_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "mode_id",
                "Configuration",
                "Runs",
                "Behavior preserved",
                "Cycle broken",
                "Local improvement",
                "Success",
            ]
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id]
        denom = int(len(mode_df))

        behavior_n = int(mode_df["behavior_preserved"].sum()) if denom else 0
        cycle_broken_n = int(mode_df["cycle_broken"].sum()) if denom else 0
        local_improvement_n = int(mode_df["local_improvement"].sum()) if denom else 0
        success_n = int(mode_df["success"].sum()) if denom else 0

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Runs": denom,
                "Behavior preserved": pct(behavior_n, denom),
                "Cycle broken": pct(cycle_broken_n, denom),
                "Local improvement": pct(local_improvement_n, denom),
                "Success": pct(success_n, denom),
            }
        )

    return pd.DataFrame(rows)


def write_main_results_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_main_results_rows(all_runs_csv_path)
    out_path = outdir / "main_results.csv"
    write_dataframe_csv(out_path, df)
    return out_path