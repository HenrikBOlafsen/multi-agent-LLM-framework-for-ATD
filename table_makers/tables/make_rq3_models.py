from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import load_all_runs_df
from metrics.metrics_difficulty import add_difficulty_metrics


CYCLE_DIFFICULTY_COLUMNS = [
    "Pooled_success_rate_bin",
    "Cycles",
    "Baseline_success_pct",
    "Selected_success_pct",
]

SINGLE_FACTOR_COLUMNS = [
    "Structural_dimension",
    "Coefficient",
    "Odds_ratio",
    "CI_95_odds_ratio",
]


def _empty_cycle_difficulty_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Pooled_success_rate_bin": "0%"},
            {"Pooled_success_rate_bin": ">0--10%"},
            {"Pooled_success_rate_bin": ">10--25%"},
            {"Pooled_success_rate_bin": ">25--50%"},
            {"Pooled_success_rate_bin": ">50--75%"},
            {"Pooled_success_rate_bin": ">75--<100%"},
            {"Pooled_success_rate_bin": "100%"},
        ],
        columns=CYCLE_DIFFICULTY_COLUMNS,
    )


def _empty_single_factor_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Structural_dimension": "Cycle size"},
            {"Structural_dimension": "Cycle centrality"},
            {"Structural_dimension": "Enclosing SCC size"},
            {"Structural_dimension": "Repository size"},
            {"Structural_dimension": "Cycle external connectivity"},
        ],
        columns=SINGLE_FACTOR_COLUMNS,
    )


def _remove_obsolete_outputs(outdir: Path) -> None:
    obsolete = [
        "eval_rq3_cycle_summary.csv",
        "eval_rq3_importance.csv",
        "eval_rq3_cycle_improvement.csv",
        "eval_rq3_cycle_improvement_by_cycle.csv",
        "eval_rq3_cycle_improvement_importance.csv",
        "eval_rq3_configuration_slopes.csv",
        "eval_rq3_configuration_interactions.csv",
        "eval_scc_marginal_effects.csv",
        "eval_rq3_regression.csv",
        "eval_rq3_predictor_scaling.csv",
    ]

    for filename in obsolete:
        path = outdir / filename
        if path.exists():
            path.unlink()


def _write_empty_outputs(outdir: Path) -> List[Path]:
    _remove_obsolete_outputs(outdir)

    paths = [
        outdir / "eval_rq3_cycle_difficulty.csv",
        outdir / "eval_rq3_single_factor_models.csv",
    ]

    write_dataframe_csv(paths[0], _empty_cycle_difficulty_rows())
    write_dataframe_csv(paths[1], _empty_single_factor_rows())

    return paths


def _prepare_model_input(all_runs_csv_path: Path) -> pd.DataFrame:
    df = add_difficulty_metrics(load_all_runs_df(all_runs_csv_path))

    required = [
        "repo",
        "cycle_id",
        "mode_id",
        "success",
        "cycle_size",
        "cycle_centrality",
        "baseline_scc_size",
        "repo_dependency_graph_size",
        "cycle_external_edges",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build RQ3 model tables because all_runs.csv is missing columns: "
            + ", ".join(missing)
        )

    return df[required].copy()


def write_rq3_model_csvs(
    all_runs_csv_path: Path,
    outdir: Path,
) -> List[Path]:
    """
    Writes the RQ3 model outputs used by the thesis results section:

    - eval_rq3_cycle_difficulty.csv
    - eval_rq3_single_factor_models.csv

    The separate structural-bin table is produced by make_rq3_structural_bins.py.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    _remove_obsolete_outputs(outdir)

    df = _prepare_model_input(all_runs_csv_path)

    if df.empty:
        return _write_empty_outputs(outdir)

    mode_ids = sorted(df["mode_id"].dropna().astype(str).unique())
    non_baseline_modes = [mode_id for mode_id in mode_ids if mode_id != "no_explain"]

    if "no_explain" not in mode_ids or len(non_baseline_modes) != 1:
        print(
            "[analysis] skipped RQ3 model tables because this analysis does not "
            "contain exactly one baseline mode and one selected mode.",
            file=sys.stderr,
        )
        return _write_empty_outputs(outdir)

    rscript = shutil.which("Rscript")
    if rscript is None:
        print(
            "[analysis] skipped RQ3 model tables because Rscript was not found.",
            file=sys.stderr,
        )
        return _write_empty_outputs(outdir)

    r_script_path = Path(__file__).resolve().parents[1] / "stats" / "rq3_glmm_lme4.R"
    if not r_script_path.exists():
        raise FileNotFoundError(f"Missing R script: {r_script_path}")

    with tempfile.TemporaryDirectory(prefix="rq3_model_input_") as tmpdir_raw:
        input_csv = Path(tmpdir_raw) / "rq3_model_input.csv"
        df.to_csv(input_csv, index=False)

        proc = subprocess.run(
            [
                rscript,
                str(r_script_path),
                str(input_csv),
                str(outdir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    if proc.stdout.strip():
        print(proc.stdout.strip(), file=sys.stderr)
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)

    if proc.returncode != 0:
        print(
            f"[analysis] RQ3 model script failed with exit code {proc.returncode}; "
            "writing placeholder CSVs.",
            file=sys.stderr,
        )
        return _write_empty_outputs(outdir)

    paths = [
        outdir / "eval_rq3_cycle_difficulty.csv",
        outdir / "eval_rq3_single_factor_models.csv",
    ]

    missing_outputs = [path for path in paths if not path.exists()]
    if missing_outputs:
        raise FileNotFoundError(
            "RQ3 model script completed but did not write expected outputs: "
            + ", ".join(str(path) for path in missing_outputs)
        )

    return paths