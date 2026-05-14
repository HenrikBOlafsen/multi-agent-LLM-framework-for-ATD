from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


def _bin_cycle_size(value: object) -> Optional[str]:
    if pd.isna(value):
        return None

    try:
        n = int(value)
    except (TypeError, ValueError):
        return None

    if 2 <= n <= 3:
        return "2--3"
    if 4 <= n <= 6:
        return "4--6"
    if 7 <= n <= 8:
        return "7--8"
    return None


def _display_configuration(mode_id: str, mode_label: str, mode_ids: list[str]) -> str:
    if mode_id == "no_explain":
        return "baseline"

    if len(mode_ids) == 2 and "no_explain" in mode_ids:
        return "selected"

    return mode_label


def _cycle_size_mode_sort_key(cycle_size_bin: str, mode_id: str) -> tuple[int, int]:
    bin_rank = {
        "2--3": 0,
        "4--6": 1,
        "7--8": 2,
    }.get(str(cycle_size_bin), 999)

    mode_rank = 0 if mode_id == "no_explain" else 1
    return bin_rank, mode_rank


def build_cycle_size_breakdown_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    empty_columns = [
        "mode_id",
        "cycle_size_bin",
        "Cycle size",
        "Runs",
        "Behavior preserved",
        "Cycle broken",
        "Local improvement",
        "Success",
    ]

    if df.empty:
        return pd.DataFrame(columns=empty_columns)

    if "cycle_size" not in df.columns:
        return pd.DataFrame(columns=empty_columns)

    df = df.copy()
    df["cycle_size_bin"] = df["cycle_size"].apply(_bin_cycle_size)
    df = df[df["cycle_size_bin"].notna()].copy()

    if df.empty:
        return pd.DataFrame(columns=empty_columns)

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)
    cycle_size_bins = ["2--3", "4--6", "7--8"]

    rows: List[Dict[str, object]] = []

    for cycle_size_bin in cycle_size_bins:
        bin_df = df[df["cycle_size_bin"] == cycle_size_bin]

        for mode_id in mode_ids:
            subgroup_df = bin_df[bin_df["mode_id"] == mode_id]
            denom = int(len(subgroup_df))

            behavior_n = int(subgroup_df["behavior_preserved"].sum()) if denom else 0
            cycle_broken_n = int(subgroup_df["cycle_broken"].sum()) if denom else 0
            local_improvement_n = int(subgroup_df["local_improvement"].sum()) if denom else 0
            success_n = int(subgroup_df["success"].sum()) if denom else 0

            mode_label = labels.get(mode_id, mode_id)
            display_configuration = _display_configuration(mode_id, mode_label, mode_ids)

            rows.append(
                {
                    "mode_id": mode_id,
                    "cycle_size_bin": cycle_size_bin,
                    "Cycle size": f"{cycle_size_bin} ({display_configuration})",
                    "Runs": denom,
                    "Behavior preserved": pct(behavior_n, denom),
                    "Cycle broken": pct(cycle_broken_n, denom),
                    "Local improvement": pct(local_improvement_n, denom),
                    "Success": pct(success_n, denom),
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=empty_columns)

    out["_sort_key"] = out.apply(
        lambda r: _cycle_size_mode_sort_key(str(r["cycle_size_bin"]), str(r["mode_id"])),
        axis=1,
    )
    out = out.sort_values(by="_sort_key", kind="stable").drop(columns=["_sort_key"])

    return out.reset_index(drop=True)


def write_cycle_size_breakdown_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_cycle_size_breakdown_rows(all_runs_csv_path)
    out_path = outdir / "cycle_size_breakdown.csv"
    write_dataframe_csv(out_path, df)
    return out_path