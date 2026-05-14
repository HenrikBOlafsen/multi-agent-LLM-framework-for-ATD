from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


RUN_ACCOUNTING_COLUMNS = [
    "mode_id",
    "Configuration",
    "Runs",
    "Structurally evaluable",
    "Other incomplete",
]


def build_run_accounting_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(columns=RUN_ACCOUNTING_COLUMNS)

    required = [
        "mode_id",
        "mode_label",
        "structurally_evaluable",
        "other_incomplete",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build run-accounting table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id]

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Runs": int(len(mode_df)),
                "Structurally evaluable": int(mode_df["structurally_evaluable"].sum()),
                "Other incomplete": int(mode_df["other_incomplete"].sum()),
            }
        )

    return pd.DataFrame(rows, columns=RUN_ACCOUNTING_COLUMNS)


def write_run_accounting_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_run_accounting_rows(all_runs_csv_path)
    out_path = outdir / "run_accounting.csv"
    write_dataframe_csv(out_path, df)
    return out_path