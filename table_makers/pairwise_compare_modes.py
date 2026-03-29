#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import math
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pandas as pd


def safe_wilcoxon_one_sample(xs: List[float], alternative: str = "greater") -> Optional[float]:
    xs = [float(v) for v in xs if v is not None and not (math.isnan(v) or math.isinf(v))]
    if not xs:
        return None
    if all(v == 0.0 for v in xs):
        return 1.0
    try:
        from scipy.stats import wilcoxon

        _, p = wilcoxon(xs, zero_method="wilcox", correction=False, alternative=alternative, mode="auto")
        return float(p)
    except Exception:
        return None


def sign_test_one_sided_greater(xs: List[float]) -> Optional[float]:
    try:
        from scipy.stats import binomtest
    except Exception:
        return None

    nonzero = [v for v in xs if v is not None and v != 0.0 and not (math.isnan(v) or math.isinf(v))]
    if not nonzero:
        return 1.0

    k_pos = sum(1 for v in nonzero if v > 0.0)
    return float(binomtest(k_pos, n=len(nonzero), p=0.5, alternative="greater").pvalue)


def bootstrap_ci_mean(
    xs: List[float],
    iters: int = 20000,
    conf: float = 0.95,
    seed: int = 0,
) -> Tuple[Optional[float], Optional[float]]:
    xs = [float(v) for v in xs if v is not None and not (math.isnan(v) or math.isinf(v))]
    if not xs:
        return (None, None)

    rnd = random.Random(seed)
    n = len(xs)
    means: List[float] = []
    for _ in range(iters):
        sample = [xs[rnd.randrange(n)] for __ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    lo_q = (1.0 - conf) / 2.0
    hi_q = 1.0 - lo_q
    lo_i = int(lo_q * (len(means) - 1))
    hi_i = int(hi_q * (len(means) - 1))
    return (means[lo_i], means[hi_i])


def holm_adjust(pvals: Sequence[Optional[float]]) -> List[Optional[float]]:
    """
    Holm-Bonferroni adjusted p-values.
    Keeps None values as None.
    """
    indexed = [(i, p) for i, p in enumerate(pvals) if p is not None and not math.isnan(p)]
    out: List[Optional[float]] = [None] * len(pvals)

    if not indexed:
        return out

    indexed.sort(key=lambda t: t[1])
    m = len(indexed)

    raw_adj = [0.0] * m
    for rank, (_idx, p) in enumerate(indexed):
        raw_adj[rank] = min(1.0, (m - rank) * float(p))

    monotone = [0.0] * m
    monotone[0] = raw_adj[0]
    for i in range(1, m):
        monotone[i] = max(monotone[i - 1], raw_adj[i])

    for (rank, (orig_idx, _p)) in enumerate(indexed):
        out[orig_idx] = min(1.0, monotone[rank])

    return out


def orient_pair(a: str, b: str) -> Tuple[str, str]:
    """
    Keep pair orientation readable:
    - no_explain is always reference when present
    - otherwise preserve lexical order for determinism
    """
    if a == "no_explain" and b != "no_explain":
        return (a, b)
    if b == "no_explain" and a != "no_explain":
        return (b, a)
    return (a, b) if a <= b else (b, a)


def parse_pairs(
    available_modes: Sequence[str],
    pair_args: Sequence[str],
) -> List[Tuple[str, str]]:
    if not pair_args or pair_args == ["all"]:
        raw_pairs = list(itertools.combinations(sorted(available_modes), 2))
        return [orient_pair(a, b) for a, b in raw_pairs]

    out: List[Tuple[str, str]] = []
    seen = set()

    for raw in pair_args:
        if ":" not in raw:
            raise SystemExit(f"Bad --pairs value {raw!r}. Expected MODE_A:MODE_B or use --pairs all")
        a, b = raw.split(":", 1)
        a = a.strip()
        b = b.strip()
        if not a or not b:
            raise SystemExit(f"Bad --pairs value {raw!r}")
        if a == b:
            raise SystemExit(f"Bad --pairs value {raw!r}: identical modes")
        if a not in available_modes or b not in available_modes:
            raise SystemExit(f"Bad --pairs value {raw!r}: modes must be among {sorted(available_modes)}")

        pair = orient_pair(a, b)
        if pair not in seen:
            out.append(pair)
            seen.add(pair)

    return out


def run_pairwise_glmm(
    df: pd.DataFrame,
    reference_mode: str,
    comparison_mode: str,
    r_script_path: Path,
) -> dict:
    slim = df.loc[:, ["repo", "cycle_id", "mode", "succ"]].copy()
    with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", delete=True) as tmp:
        slim.to_csv(tmp.name, index=False)
        proc = subprocess.run(
            ["Rscript", str(r_script_path), tmp.name, "pairwise", reference_mode, comparison_mode],
            capture_output=True,
            text=True,
            check=False,
        )

    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)

    if proc.returncode != 0:
        return {
            "glmm_method": None,
            "glmm_reference_mode": reference_mode,
            "glmm_comparison_mode": comparison_mode,
            "glmm_note": proc.stderr.strip() or proc.stdout.strip() or f"R exit code {proc.returncode}",
            "glmm_beta": None,
            "glmm_se": None,
            "glmm_z": None,
            "glmm_wald_p_two_sided": None,
            "glmm_lrt_p": None,
            "glmm_odds_ratio": None,
            "glmm_odds_ratio_ci_lo_95": None,
            "glmm_odds_ratio_ci_hi_95": None,
            "glmm_n_obs": None,
            "glmm_converged": None,
            "glmm_singular": None,
            "glmm_n_cycle": None,
        }

    parsed = pd.read_csv(pd.io.common.StringIO(proc.stdout))
    if parsed.empty:
        return {
            "glmm_method": None,
            "glmm_reference_mode": reference_mode,
            "glmm_comparison_mode": comparison_mode,
            "glmm_note": "Empty R output",
            "glmm_beta": None,
            "glmm_se": None,
            "glmm_z": None,
            "glmm_wald_p_two_sided": None,
            "glmm_lrt_p": None,
            "glmm_odds_ratio": None,
            "glmm_odds_ratio_ci_lo_95": None,
            "glmm_odds_ratio_ci_hi_95": None,
            "glmm_n_obs": None,
            "glmm_converged": None,
            "glmm_singular": None,
            "glmm_n_cycle": None,
        }

    row = parsed.iloc[0].to_dict()
    return {
        "glmm_method": row.get("method"),
        "glmm_reference_mode": row.get("reference_mode", reference_mode),
        "glmm_comparison_mode": row.get("comparison_mode", comparison_mode),
        "glmm_note": row.get("glmm_note"),
        "glmm_beta": row.get("beta"),
        "glmm_se": row.get("se"),
        "glmm_z": row.get("z"),
        "glmm_wald_p_two_sided": row.get("wald_p_two_sided"),
        "glmm_lrt_p": row.get("lrt_p"),
        "glmm_odds_ratio": row.get("odds_ratio"),
        "glmm_odds_ratio_ci_lo_95": row.get("or_ci_lo_95"),
        "glmm_odds_ratio_ci_hi_95": row.get("or_ci_hi_95"),
        "glmm_n_obs": row.get("n_obs"),
        "glmm_converged": row.get("converged"),
        "glmm_singular": row.get("singular"),
        "glmm_n_cycle": row.get("n_cycle"),
    }


def build_cycle_pairwise(df: pd.DataFrame, reference_mode: str, comparison_mode: str) -> pd.DataFrame:
    ref = (
        df.loc[df["mode"] == reference_mode, ["repo", "cycle_id", "cycle_size", "succ"]]
        .groupby(["repo", "cycle_id", "cycle_size"], dropna=False)["succ"]
        .mean()
        .reset_index(name="succ_rate_reference")
    )

    cmp = (
        df.loc[df["mode"] == comparison_mode, ["repo", "cycle_id", "cycle_size", "succ"]]
        .groupby(["repo", "cycle_id", "cycle_size"], dropna=False)["succ"]
        .mean()
        .reset_index(name="succ_rate_comparison")
    )

    merged = pd.merge(ref, cmp, on=["repo", "cycle_id", "cycle_size"], how="outer")
    merged["reference_mode"] = reference_mode
    merged["comparison_mode"] = comparison_mode
    merged["diff_comparison_minus_reference"] = (
        merged["succ_rate_comparison"] - merged["succ_rate_reference"]
    )
    return merged


def summarize_pair(df: pd.DataFrame, reference_mode: str, comparison_mode: str, r_script_path: Path) -> dict:
    pair_df = df[df["mode"].isin([reference_mode, comparison_mode])].copy()
    cycle_df = build_cycle_pairwise(pair_df, reference_mode, comparison_mode)
    diffs = cycle_df["diff_comparison_minus_reference"].dropna().astype(float).tolist()

    ref_runs = pair_df[pair_df["mode"] == reference_mode]
    cmp_runs = pair_df[pair_df["mode"] == comparison_mode]

    ref_micro = 100.0 * float(ref_runs["succ"].mean()) if len(ref_runs) else None
    cmp_micro = 100.0 * float(cmp_runs["succ"].mean()) if len(cmp_runs) else None

    ref_macro_vals = cycle_df["succ_rate_reference"].dropna().astype(float)
    cmp_macro_vals = cycle_df["succ_rate_comparison"].dropna().astype(float)

    ref_macro = 100.0 * float(ref_macro_vals.mean()) if len(ref_macro_vals) else None
    cmp_macro = 100.0 * float(cmp_macro_vals.mean()) if len(cmp_macro_vals) else None

    mean_diff = float(sum(diffs) / len(diffs)) if diffs else None
    med_diff = float(pd.Series(diffs).median()) if diffs else None
    diff_std = float(pd.Series(diffs).std(ddof=1)) if len(diffs) >= 2 else None
    ci_lo, ci_hi = bootstrap_ci_mean(diffs) if diffs else (None, None)
    wil_p = safe_wilcoxon_one_sample(diffs, alternative="greater")
    sign_p = sign_test_one_sided_greater(diffs)

    nonzero = [d for d in diffs if d != 0.0]
    n_cmp_better = sum(1 for d in nonzero if d > 0.0)
    n_ref_better = sum(1 for d in nonzero if d < 0.0)

    glmm = run_pairwise_glmm(pair_df, reference_mode, comparison_mode, r_script_path)

    row = {
        "reference_mode": reference_mode,
        "comparison_mode": comparison_mode,
        "reference_micro_success_pct": ref_micro,
        "comparison_micro_success_pct": cmp_micro,
        "reference_macro_success_pct": ref_macro,
        "comparison_macro_success_pct": cmp_macro,
        "n_cycles": len(diffs),
        "n_cycles_comparison_better": n_cmp_better,
        "n_cycles_reference_better": n_ref_better,
        "diff_comparison_minus_reference_mean": mean_diff,
        "diff_comparison_minus_reference_median": med_diff,
        "diff_comparison_minus_reference_std": diff_std,
        "diff_mean_bootstrap_ci_lo": ci_lo,
        "diff_mean_bootstrap_ci_hi": ci_hi,
        "p_wilcoxon_one_sided_greater": wil_p,
        "p_sign_test_one_sided_greater": sign_p,
    }
    row.update(glmm)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Run pairwise comparisons from all_runs.csv.")
    ap.add_argument("--input", required=True, help="Path to all_runs.csv")
    ap.add_argument("--outdir", required=True)
    ap.add_argument(
        "--pairs",
        nargs="*",
        default=["all"],
        help="Either 'all' or repeated MODE_A:MODE_B",
    )
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_path)
    if df.empty:
        raise SystemExit("Input CSV is empty.")

    df["succ"] = df["succ"].astype(str).str.strip().str.lower().map(
        {"true": True, "false": False, "1": True, "0": False}
    )

    modes = sorted(df["mode"].dropna().astype(str).unique())
    if len(modes) < 2:
        raise SystemExit("Need at least two modes in the input CSV.")

    pairs = parse_pairs(modes, args.pairs)
    r_script = Path(__file__).resolve().parent / "glmm_cycle_mode_lme4.R"

    summary_rows = []
    cycle_pair_frames = []

    for reference_mode, comparison_mode in pairs:
        pair_df = df[df["mode"].isin([reference_mode, comparison_mode])].copy()

        cycle_df = build_cycle_pairwise(pair_df, reference_mode, comparison_mode)
        cycle_pair_frames.append(cycle_df)

        summary_rows.append(
            summarize_pair(df, reference_mode, comparison_mode, r_script)
        )

    summary_out = pd.DataFrame(summary_rows)

    if not summary_out.empty:
        summary_out["p_wilcoxon_one_sided_greater_holm"] = holm_adjust(
            summary_out["p_wilcoxon_one_sided_greater"].tolist()
        )
        summary_out["p_sign_test_one_sided_greater_holm"] = holm_adjust(
            summary_out["p_sign_test_one_sided_greater"].tolist()
        )

        sort_key = pd.Series(range(len(summary_out)), index=summary_out.index)
        if "reference_mode" in summary_out.columns:
            sort_key = sort_key.where(summary_out["reference_mode"] != "no_explain", -1000)
        summary_out = summary_out.sort_values(
            by=["reference_mode", "comparison_mode"],
            kind="stable",
        ).reset_index(drop=True)

        if "no_explain" in summary_out["reference_mode"].values:
            noexp = summary_out[summary_out["reference_mode"] == "no_explain"]
            other = summary_out[summary_out["reference_mode"] != "no_explain"]
            summary_out = pd.concat([noexp, other], ignore_index=True)

    summary_path = outdir / "pairwise_summary.csv"
    summary_out.to_csv(summary_path, index=False)
    print(f"Wrote: {summary_path}", file=sys.stderr)

    cycle_out = pd.concat(cycle_pair_frames, ignore_index=True) if cycle_pair_frames else pd.DataFrame()
    if not cycle_out.empty:
        cycle_out = cycle_out.sort_values(
            by=["reference_mode", "comparison_mode", "repo", "cycle_id"],
            kind="stable",
        ).reset_index(drop=True)

        if "no_explain" in cycle_out["reference_mode"].values:
            noexp = cycle_out[cycle_out["reference_mode"] == "no_explain"]
            other = cycle_out[cycle_out["reference_mode"] != "no_explain"]
            cycle_out = pd.concat([noexp, other], ignore_index=True)

    cycle_path = outdir / "pairwise_cycle_differences.csv"
    cycle_out.to_csv(cycle_path, index=False)
    print(f"Wrote: {cycle_path}", file=sys.stderr)


if __name__ == "__main__":
    main()