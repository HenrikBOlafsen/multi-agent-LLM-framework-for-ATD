from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from core.io_utils import read_dataframe_csv


def load_all_runs_df(all_runs_csv_path: Path) -> pd.DataFrame:
    return read_dataframe_csv(all_runs_csv_path)


def build_mode_label_map(df: pd.DataFrame) -> Dict[str, str]:
    if df.empty:
        return {}

    return (
        df[["mode_id", "mode_label"]]
        .drop_duplicates()
        .set_index("mode_id")["mode_label"]
        .to_dict()
    )


def present_mode_ids(df: pd.DataFrame) -> list[str]:
    if df.empty or "mode_id" not in df.columns:
        return []
    return list(df["mode_id"].drop_duplicates())