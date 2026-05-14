# table_makers/tables/make_openhands_iteration_limit.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from core.io_utils import pct, write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


MAX_ITERATIONS = 150

ITERATION_LIMIT_COLUMNS = [
    "mode_id",
    "Configuration",
    "Runs",
    "Runs with trajectory",
    "Reached 150 model responses",
    "Reached 150 model responses (%)",
    "Reached 150 without finish",
    "Reached 150 without finish (%)",
]


def _trajectory_path_from_row(row: pd.Series) -> Path:
    return Path(str(row["branch_results_dir"])) / "openhands" / "trajectory.json"


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    return [item for item in data if isinstance(item, dict)]


def _model_response_id(event: dict[str, Any]) -> str | None:
    metadata = event.get("tool_call_metadata")
    if not isinstance(metadata, dict):
        return None

    model_response = metadata.get("model_response")
    if not isinstance(model_response, dict):
        return None

    response_id = model_response.get("id")
    if not isinstance(response_id, str) or not response_id.strip():
        return None

    return response_id.strip()


def _has_finish_action(event: dict[str, Any]) -> bool:
    if event.get("action") == "finish":
        return True

    metadata = event.get("tool_call_metadata")
    if not isinstance(metadata, dict):
        return False

    return metadata.get("function_name") == "finish"


def _trajectory_summary(path: Path) -> dict[str, object]:
    events = _read_json_list(path)

    if not events:
        return {
            "has_trajectory": False,
            "model_responses": 0,
            "has_finish": False,
            "reached_150": False,
            "reached_150_without_finish": False,
        }

    response_ids = {
        response_id
        for event in events
        if (response_id := _model_response_id(event)) is not None
    }

    model_responses = len(response_ids)
    has_finish = any(_has_finish_action(event) for event in events)
    reached_150 = model_responses >= MAX_ITERATIONS

    return {
        "has_trajectory": True,
        "model_responses": model_responses,
        "has_finish": has_finish,
        "reached_150": reached_150,
        "reached_150_without_finish": reached_150 and not has_finish,
    }


def build_openhands_iteration_limit_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(columns=ITERATION_LIMIT_COLUMNS)

    required = ["mode_id", "mode_label", "branch_results_dir"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build OpenHands iteration-limit table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    df = df.copy()
    summaries = df.apply(
        lambda row: _trajectory_summary(_trajectory_path_from_row(row)),
        axis=1,
    )

    df["has_trajectory"] = summaries.apply(lambda x: bool(x["has_trajectory"]))
    df["reached_150"] = summaries.apply(lambda x: bool(x["reached_150"]))
    df["reached_150_without_finish"] = summaries.apply(
        lambda x: bool(x["reached_150_without_finish"])
    )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id]
        runs = int(len(mode_df))
        runs_with_trajectory = int(mode_df["has_trajectory"].sum())
        reached_150_n = int(mode_df["reached_150"].sum())
        reached_150_without_finish_n = int(mode_df["reached_150_without_finish"].sum())

        rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Runs": runs,
                "Runs with trajectory": runs_with_trajectory,
                "Reached 150 model responses": reached_150_n,
                "Reached 150 model responses (%)": pct(reached_150_n, runs),
                "Reached 150 without finish": reached_150_without_finish_n,
                "Reached 150 without finish (%)": pct(
                    reached_150_without_finish_n,
                    runs,
                ),
            }
        )

    return pd.DataFrame(rows, columns=ITERATION_LIMIT_COLUMNS)


def write_openhands_iteration_limit_csv(
    all_runs_csv_path: Path,
    outdir: Path,
) -> Path:
    df = build_openhands_iteration_limit_rows(all_runs_csv_path)
    out_path = outdir / "openhands_iteration_limit.csv"
    write_dataframe_csv(out_path, df)
    return out_path