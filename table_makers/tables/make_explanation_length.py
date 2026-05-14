from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


EXPLANATION_LENGTH_COLUMNS = [
    "mode_id",
    "Configuration",
    "Mean expl. chars",
    "Median expl. chars",
]


def _median_as_int(series: pd.Series) -> int | None:
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    return int(round(float(cleaned.median())))


def _mean_as_int(series: pd.Series) -> int | None:
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    return int(round(float(cleaned.mean())))


def build_explanation_length_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(columns=EXPLANATION_LENGTH_COLUMNS)

    if "explanation_chars" not in df.columns:
        return pd.DataFrame(columns=EXPLANATION_LENGTH_COLUMNS)

    df = df[df["explanation_chars"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=EXPLANATION_LENGTH_COLUMNS)

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id]

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Mean expl. chars": _mean_as_int(mode_df["explanation_chars"]),
                "Median expl. chars": _median_as_int(mode_df["explanation_chars"]),
            }
        )

    return pd.DataFrame(rows, columns=EXPLANATION_LENGTH_COLUMNS)


def write_explanation_length_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_explanation_length_rows(all_runs_csv_path)
    out_path = outdir / "explanation_length.csv"
    write_dataframe_csv(out_path, df)
    return out_path