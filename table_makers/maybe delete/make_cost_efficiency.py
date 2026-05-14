from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


def _positive(series: pd.Series) -> pd.Series:
    s = series.dropna()
    if s.empty:
        return s
    return s[s > 0]


def _mean(series: pd.Series) -> int | None:
    s = _positive(series)
    if s.empty:
        return None
    return int(round(float(s.mean())))


def _iqr(series: pd.Series) -> int | None:
    s = _positive(series)
    if s.empty:
        return None
    q1 = float(s.quantile(0.25))
    q3 = float(s.quantile(0.75))
    return int(round(q3 - q1))


def build_cost_efficiency_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "mode_id",
                "Configuration",
                "Mean tokens (all runs)",
                "IQR tokens (all runs)",
                "Mean tokens (success)",
                "Mean tokens (failure)",
            ]
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id]

        success_df = mode_df[mode_df["success"] == 1]
        failure_df = mode_df[mode_df["success"] == 0]

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Mean tokens (all runs)": _mean(mode_df["total_tokens"]),
                "IQR tokens (all runs)": _iqr(mode_df["total_tokens"]),
                "Mean tokens (success)": _mean(success_df["total_tokens"]),
                "Mean tokens (failure)": _mean(failure_df["total_tokens"]),
            }
        )

    return pd.DataFrame(rows)


def write_cost_efficiency_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_cost_efficiency_rows(all_runs_csv_path)
    out_path = outdir / "cost_efficiency.csv"
    write_dataframe_csv(out_path, df)
    return out_path