from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


def _median(series: pd.Series) -> float | None:
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    return float(round(float(cleaned.median()), 1))


def _iqr(series: pd.Series) -> float | None:
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    q1 = float(cleaned.quantile(0.25))
    q3 = float(cleaned.quantile(0.75))
    return float(round(q3 - q1, 1))


def build_edit_footprint_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "mode_id",
                "Configuration",
                "Median files modified",
                "IQR files modified",
                "Median chars changed",
                "IQR chars changed",
                "Median chars changed (succ. only)",
            ]
        )

    required_columns = {"files_modified", "chars_changed"}
    if not required_columns.issubset(df.columns):
        return pd.DataFrame(
            columns=[
                "mode_id",
                "Configuration",
                "Median files modified",
                "IQR files modified",
                "Median chars changed",
                "IQR chars changed",
                "Median chars changed (succ. only)",
            ]
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id].copy()
        success_df = mode_df[mode_df["success"] == 1].copy()

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Median files modified": _median(mode_df["files_modified"]),
                "IQR files modified": _iqr(mode_df["files_modified"]),
                "Median chars changed": _median(mode_df["chars_changed"]),
                "IQR chars changed": _iqr(mode_df["chars_changed"]),
                "Median chars changed (succ. only)": _median(success_df["chars_changed"]),
            }
        )

    return pd.DataFrame(rows)


def write_edit_footprint_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_edit_footprint_rows(all_runs_csv_path)
    out_path = outdir / "edit_footprint.csv"
    write_dataframe_csv(out_path, df)
    return out_path