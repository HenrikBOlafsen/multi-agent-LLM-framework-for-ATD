from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import load_all_runs_df


REGRESSION_COLUMNS = [
    "Effect",
    "Coefficient",
    "Odds_ratio",
    "CI_95_odds_ratio",
    "p",
]


def _empty_eval_regression_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Effect": "Configuration (Advisory)"},
            {"Effect": "Cycle random-effect variance"},
            {"Effect": "Repository random-effect variance (robustness model)"},
        ],
        columns=REGRESSION_COLUMNS,
    )


def _write_empty_output(outdir: Path) -> Path:
    out_path = outdir / "eval_regression.csv"
    write_dataframe_csv(out_path, _empty_eval_regression_rows())
    return out_path


def _prepare_model_input(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    required = [
        "repo",
        "cycle_id",
        "mode_id",
        "success",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build final-evaluation regression table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    return df[required].copy()


def write_eval_regression_csv(
    all_runs_csv_path: Path,
    outdir: Path,
) -> Path:
    """
    Writes eval_regression.csv for the final evaluation regression table.

    This assumes exactly:
    - one no_explain baseline mode
    - one selected explanation mode

    The R script fits:
        cbind(successes, failures) ~ selected_system + (1 | cycle)

    and reports the configuration p-value from a likelihood-ratio test against:
        cbind(successes, failures) ~ 1 + (1 | cycle)
    """
    outdir.mkdir(parents=True, exist_ok=True)

    df = _prepare_model_input(all_runs_csv_path)

    if df.empty:
        return _write_empty_output(outdir)

    mode_ids = sorted(df["mode_id"].dropna().astype(str).unique())
    non_baseline_modes = [mode_id for mode_id in mode_ids if mode_id != "no_explain"]

    if "no_explain" not in mode_ids or len(non_baseline_modes) != 1:
        print(
            "[analysis] skipped final-evaluation regression because this analysis "
            "does not contain exactly one baseline mode and one selected mode.",
            file=sys.stderr,
        )
        return _write_empty_output(outdir)

    rscript = shutil.which("Rscript")
    if rscript is None:
        print(
            "[analysis] skipped final-evaluation regression because Rscript was not found.",
            file=sys.stderr,
        )
        return _write_empty_output(outdir)

    r_script_path = Path(__file__).resolve().parents[1] / "stats" / "eval_glmm_lme4.R"
    if not r_script_path.exists():
        raise FileNotFoundError(f"Missing R script: {r_script_path}")

    with tempfile.TemporaryDirectory(prefix="eval_glmm_input_") as tmpdir_raw:
        input_csv = Path(tmpdir_raw) / "eval_glmm_input.csv"
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
            f"[analysis] final-evaluation regression failed with exit code "
            f"{proc.returncode}; writing placeholder CSV.",
            file=sys.stderr,
        )
        return _write_empty_output(outdir)

    out_path = outdir / "eval_regression.csv"

    if not out_path.exists():
        raise FileNotFoundError(
            "Final-evaluation regression script completed but did not write "
            f"expected output: {out_path}"
        )

    return out_path