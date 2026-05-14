from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import load_all_runs_df


PAIRWISE_COLUMNS = [
    "Comparison",
    "Left mode",
    "Right mode",
    "Paired cycles",
    "Delta mean (pp)",
    "CI low (pp)",
    "CI high (pp)",
]


@dataclass(frozen=True)
class PairwiseComparison:
    left_mode: str
    right_mode: str
    label: str


PARADIGM_COMPARISONS = [
    PairwiseComparison(
        left_mode="explain_E0_S0_noaux",
        right_mode="no_explain",
        label="Descriptive vs No-explanation",
    ),
    PairwiseComparison(
        left_mode="explain_E1_S1_noaux",
        right_mode="no_explain",
        label="Advisory vs No-explanation",
    ),
    PairwiseComparison(
        left_mode="explain_E2_S2_noaux",
        right_mode="no_explain",
        label="Directive vs No-explanation",
    ),
    PairwiseComparison(
        left_mode="explain_E0_S0_noaux",
        right_mode="explain_E1_S1_noaux",
        label="Descriptive vs Advisory",
    ),
    PairwiseComparison(
        left_mode="explain_E0_S0_noaux",
        right_mode="explain_E2_S2_noaux",
        label="Descriptive vs Directive",
    ),
    PairwiseComparison(
        left_mode="explain_E1_S1_noaux",
        right_mode="explain_E2_S2_noaux",
        label="Advisory vs Directive",
    ),
]


AUXILIARY_COMPARISONS = [
    PairwiseComparison(
        left_mode="explain_E1_S1_boundary",
        right_mode="explain_E1_S1_noaux",
        label="Advisory + boundary vs Advisory",
    ),
    PairwiseComparison(
        left_mode="explain_E1_S1_graph",
        right_mode="explain_E1_S1_noaux",
        label="Advisory + graph vs Advisory",
    ),
    PairwiseComparison(
        left_mode="explain_E2_S2_boundary",
        right_mode="explain_E2_S2_noaux",
        label="Directive + boundary vs Directive",
    ),
    PairwiseComparison(
        left_mode="explain_E2_S2_graph",
        right_mode="explain_E2_S2_noaux",
        label="Directive + graph vs Directive",
    ),
]


def _select_comparisons(mode_ids: set[str]) -> List[PairwiseComparison]:
    comparisons = PARADIGM_COMPARISONS + AUXILIARY_COMPARISONS
    return [
        comparison
        for comparison in comparisons
        if comparison.left_mode in mode_ids and comparison.right_mode in mode_ids
    ]


def _cycle_success_rates(df: pd.DataFrame) -> pd.DataFrame:
    required = ["repo", "cycle_id", "mode_id", "success"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build cycle-level pairwise success table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    work = df[required].copy()
    work["repo"] = work["repo"].astype(str)
    work["cycle_id"] = work["cycle_id"].astype(str)
    work["mode_id"] = work["mode_id"].astype(str)
    work["success"] = (
        pd.to_numeric(work["success"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    return (
        work.groupby(["repo", "cycle_id", "mode_id"], as_index=False)
        .agg(success_rate=("success", "mean"))
    )


def _paired_differences_for_comparison(
    cycle_rates: pd.DataFrame,
    comparison: PairwiseComparison,
) -> pd.Series:
    left = cycle_rates[cycle_rates["mode_id"] == comparison.left_mode]
    right = cycle_rates[cycle_rates["mode_id"] == comparison.right_mode]

    paired = left.merge(
        right,
        on=["repo", "cycle_id"],
        how="inner",
        suffixes=("_left", "_right"),
    )

    if paired.empty:
        return pd.Series(dtype=float)

    return (
        paired["success_rate_left"] - paired["success_rate_right"]
    ) * 100.0


def _bootstrap_ci(
    values: np.ndarray,
    *,
    seed: int,
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
) -> tuple[Optional[float], Optional[float]]:
    if len(values) == 0:
        return None, None

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_bootstrap, dtype=float)

    for i in range(n_bootstrap):
        boot_means[i] = float(np.mean(rng.choice(values, size=len(values), replace=True)))

    return (
        float(np.quantile(boot_means, alpha / 2.0)),
        float(np.quantile(boot_means, 1.0 - alpha / 2.0)),
    )


def _round_or_none(value: Optional[float]) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 1)


def _stable_seed_for_label(label: str) -> int:
    return 12345 + sum(ord(ch) for ch in label)


def _build_comparison_row(
    cycle_rates: pd.DataFrame,
    comparison: PairwiseComparison,
) -> Dict[str, object]:
    deltas = _paired_differences_for_comparison(cycle_rates, comparison).to_numpy(dtype=float)

    if len(deltas) == 0:
        return {
            "Comparison": comparison.label,
            "Left mode": comparison.left_mode,
            "Right mode": comparison.right_mode,
            "Paired cycles": 0,
            "Delta mean (pp)": None,
            "CI low (pp)": None,
            "CI high (pp)": None,
        }

    ci_low, ci_high = _bootstrap_ci(
        deltas,
        seed=_stable_seed_for_label(comparison.label),
    )

    return {
        "Comparison": comparison.label,
        "Left mode": comparison.left_mode,
        "Right mode": comparison.right_mode,
        "Paired cycles": int(len(deltas)),
        "Delta mean (pp)": _round_or_none(float(np.mean(deltas))),
        "CI low (pp)": _round_or_none(ci_low),
        "CI high (pp)": _round_or_none(ci_high),
    }


def build_cycle_level_pairwise_success_rows(
    all_runs_csv_path: Path,
) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty or "mode_id" not in df.columns:
        return pd.DataFrame(columns=PAIRWISE_COLUMNS)

    comparisons = _select_comparisons(
        set(df["mode_id"].dropna().astype(str).unique())
    )

    if not comparisons:
        return pd.DataFrame(columns=PAIRWISE_COLUMNS)

    cycle_rates = _cycle_success_rates(df)

    return pd.DataFrame(
        [
            _build_comparison_row(cycle_rates, comparison)
            for comparison in comparisons
        ],
        columns=PAIRWISE_COLUMNS,
    )


def write_cycle_level_pairwise_success_csv(
    all_runs_csv_path: Path,
    outdir: Path,
) -> Path:
    df = build_cycle_level_pairwise_success_rows(all_runs_csv_path)
    out_path = outdir / "cycle_level_pairwise_success.csv"
    write_dataframe_csv(out_path, df)
    return out_path