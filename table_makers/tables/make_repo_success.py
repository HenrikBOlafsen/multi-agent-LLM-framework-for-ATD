from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


def build_repo_success_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    columns = [
        "repo",
        "mode_id",
        "Configuration",
        "Runs",
        "Successes",
        "Success",
    ]

    if df.empty:
        return pd.DataFrame(columns=columns)

    required = ["repo", "mode_id", "mode_label", "success"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build repo-success table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)
    repos = sorted(df["repo"].dropna().astype(str).unique())

    rows: List[Dict[str, object]] = []

    for repo in repos:
        repo_df = df[df["repo"].astype(str) == repo]

        for mode_id in mode_ids:
            mode_df = repo_df[repo_df["mode_id"] == mode_id]
            denom = int(len(mode_df))
            success_n = int(mode_df["success"].sum()) if denom else 0

            rows.append(
                {
                    "repo": repo,
                    "mode_id": mode_id,
                    "Configuration": labels.get(mode_id, mode_id),
                    "Runs": denom,
                    "Successes": success_n,
                    "Success": pct(success_n, denom),
                }
            )

    return pd.DataFrame(rows, columns=columns)


def write_repo_success_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_repo_success_rows(all_runs_csv_path)
    out_path = outdir / "repo_success.csv"
    write_dataframe_csv(out_path, df)
    return out_path