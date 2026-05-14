from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


STRUCTURAL_DECOMPOSITION_COLUMNS = [
    "mode_id",
    "Configuration",
    "Structural imp.",
    "Weakening imp.",
    "No local improvement",
]


def build_structural_decomposition_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(columns=STRUCTURAL_DECOMPOSITION_COLUMNS)

    required = [
        "mode_id",
        "mode_label",
        "structurally_evaluable",
        "behavior_preserved",
        "cycle_broken",
        "structural_improvement_raw",
        "weakening_improvement_raw",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build structural-decomposition table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id]

        denom_df = mode_df[
            (mode_df["structurally_evaluable"] == 1)
            & (mode_df["behavior_preserved"] == 1)
            & (mode_df["cycle_broken"] == 1)
        ]

        denom = int(len(denom_df))

        structural_n = int(denom_df["structural_improvement_raw"].sum()) if denom else 0
        weakening_n = int(denom_df["weakening_improvement_raw"].sum()) if denom else 0

        no_local_n = (
            int(
                (
                    (denom_df["structural_improvement_raw"] == 0)
                    & (denom_df["weakening_improvement_raw"] == 0)
                ).sum()
            )
            if denom
            else 0
        )

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Structural imp.": pct(structural_n, denom),
                "Weakening imp.": pct(weakening_n, denom),
                "No local improvement": pct(no_local_n, denom),
            }
        )

    return pd.DataFrame(rows, columns=STRUCTURAL_DECOMPOSITION_COLUMNS)


def write_structural_decomposition_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_structural_decomposition_rows(all_runs_csv_path)
    out_path = outdir / "structural_decomposition.csv"
    write_dataframe_csv(out_path, df)
    return out_path