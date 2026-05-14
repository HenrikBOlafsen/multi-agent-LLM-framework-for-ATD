from __future__ import annotations

import argparse
from pathlib import Path

from core.dataset_builder import write_all_runs_csv
from tables.make_cycle_size_breakdown import write_cycle_size_breakdown_csv
from tables.make_edit_footprint import write_edit_footprint_csv
from tables.make_explanation_length import write_explanation_length_csv
from tables.make_language_breakdown import write_language_breakdown_csv
from tables.make_main_results import write_main_results_csv
from tables.make_rq3_models import write_rq3_model_csvs
from tables.make_run_accounting import write_run_accounting_csv
from tables.make_structural_decomposition import write_structural_decomposition_csv
from tables.make_rq3_structural_bins import write_rq3_structural_bins_csv
from tables.make_eval_regression import write_eval_regression_csv
from tables.make_cycle_level_pairwise_success import write_cycle_level_pairwise_success_csv
from tables.make_global_regression_criteria import write_global_regression_criteria_csv
from tables.make_python_stale_import_risk import write_python_stale_import_risk_csv
from tables.make_repo_success import write_repo_success_csv
from tables.make_openhands_iteration_limit import write_openhands_iteration_limit_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--analysis-plan", required=True)
    parser.add_argument("--outdir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config_path = Path(args.config).resolve()
    analysis_plan_path = Path(args.analysis_plan).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    all_runs_path = write_all_runs_csv(
        config_path=config_path,
        analysis_plan_path=analysis_plan_path,
        outdir=outdir,
        filename="all_runs.csv",
    )
    print(f"[analysis] wrote {all_runs_path}")

    table_writers = [
        write_main_results_csv,
        write_eval_regression_csv,
        write_cycle_level_pairwise_success_csv,
        write_explanation_length_csv,
        write_structural_decomposition_csv,
        write_edit_footprint_csv,
        write_global_regression_criteria_csv,
        write_language_breakdown_csv,
        write_cycle_size_breakdown_csv,
        write_run_accounting_csv,
        write_rq3_structural_bins_csv,
        write_python_stale_import_risk_csv,
        write_repo_success_csv,
        write_openhands_iteration_limit_csv,
    ]

    for writer in table_writers:
        path = writer(
            all_runs_csv_path=all_runs_path,
            outdir=outdir,
        )
        print(f"[analysis] wrote {path}")

    rq3_model_paths = write_rq3_model_csvs(
        all_runs_csv_path=all_runs_path,
        outdir=outdir,
    )
    for path in rq3_model_paths:
        print(f"[analysis] wrote {path}")


if __name__ == "__main__":
    main()