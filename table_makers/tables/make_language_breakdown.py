from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


def _present_languages(df: pd.DataFrame) -> list[str]:
    if df.empty or "language" not in df.columns:
        return []
    return list(df["language"].dropna().drop_duplicates())


def _display_language(language: str) -> str:
    normalized = str(language).strip().lower()
    if normalized == "python":
        return "Python"
    if normalized in {"csharp", "c#", "cs", "dotnet", ".net"}:
        return "C#"
    return str(language).strip()


def _display_configuration(mode_id: str, mode_label: str, mode_ids: list[str]) -> str:
    if mode_id == "no_explain":
        return "baseline"

    # For the held-out evaluation language table, the non-baseline mode is the selected system.
    if len(mode_ids) == 2 and "no_explain" in mode_ids:
        return "selected"

    return mode_label


def _language_mode_sort_key(language: str, mode_id: str) -> tuple[int, int]:
    language_rank = {
        "python": 0,
        "csharp": 1,
        "c#": 1,
        "cs": 1,
        "dotnet": 1,
        ".net": 1,
    }.get(str(language).strip().lower(), 999)

    mode_rank = 0 if mode_id == "no_explain" else 1
    return language_rank, mode_rank


def build_language_breakdown_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "mode_id",
                "language",
                "Language",
                "Runs",
                "Behavior preserved",
                "Cycle broken",
                "Local improvement",
                "Success",
            ]
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)
    languages = _present_languages(df)

    rows: List[Dict[str, object]] = []

    for language in languages:
        language_df = df[df["language"] == language]

        for mode_id in mode_ids:
            subgroup_df = language_df[language_df["mode_id"] == mode_id]
            denom = int(len(subgroup_df))

            behavior_n = int(subgroup_df["behavior_preserved"].sum()) if denom else 0
            cycle_broken_n = int(subgroup_df["cycle_broken"].sum()) if denom else 0
            local_improvement_n = int(subgroup_df["local_improvement"].sum()) if denom else 0
            success_n = int(subgroup_df["success"].sum()) if denom else 0

            mode_label = labels.get(mode_id, mode_id)
            display_language = _display_language(language)
            display_configuration = _display_configuration(mode_id, mode_label, mode_ids)

            rows.append(
                {
                    "mode_id": mode_id,
                    "language": language,
                    "Language": f"{display_language} ({display_configuration})",
                    "Runs": denom,
                    "Behavior preserved": pct(behavior_n, denom),
                    "Cycle broken": pct(cycle_broken_n, denom),
                    "Local improvement": pct(local_improvement_n, denom),
                    "Success": pct(success_n, denom),
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["_sort_key"] = out.apply(
        lambda r: _language_mode_sort_key(str(r["language"]), str(r["mode_id"])),
        axis=1,
    )
    out = out.sort_values(by="_sort_key", kind="stable").drop(columns=["_sort_key"])

    return out.reset_index(drop=True)


def write_language_breakdown_csv(all_runs_csv_path: Path, outdir: Path) -> Path:
    df = build_language_breakdown_rows(all_runs_csv_path)
    out_path = outdir / "language_breakdown.csv"
    write_dataframe_csv(out_path, df)
    return out_path