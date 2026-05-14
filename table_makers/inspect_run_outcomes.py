from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


COLUMNS = [
    "repo",
    "experiment_id",
    "cycle_id",
    "mode_id",
    "mode_label",
    "behavior_preserved",
    "cycle_broken",
    "local_improvement",
    "success",
    "global_structural_regression_raw",
    "global_regression_outside_target_raw",
    "structurally_evaluable",
    "other_incomplete",
    "no_change",
    "openhands_outcome",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("all_runs_csv", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    df = pd.read_csv(args.all_runs_csv)

    missing = [col for col in COLUMNS if col not in df.columns]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))

    out = df[COLUMNS].rename(
        columns={
            "experiment_id": "experiment",
            "cycle_id": "cycle",
            "mode_id": "mode",
            "mode_label": "configuration",
            "behavior_preserved": "behavior",
            "cycle_broken": "cycle broken",
            "local_improvement": "local improvement",
            "global_structural_regression_raw": "global regression",
            "global_regression_outside_target_raw": "outside-target regression",
            "structurally_evaluable": "structural eval",
            "other_incomplete": "incomplete",
            "no_change": "no change",
            "openhands_outcome": "openhands outcome",
        }
    )

    out_path = args.all_runs_csv.parent / "run_outcomes.csv"
    out.to_csv(out_path, index=False)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()