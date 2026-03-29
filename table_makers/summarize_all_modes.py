#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import subprocess
import tempfile


SUCCESS_OUTCOME = "success"


def mean_or_none(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return None if s.empty else float(s.mean())


def median_or_none(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return None if s.empty else float(s.median())


def std_or_none(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return None if len(s) < 2 else float(s.std(ddof=1))


def pct(num: int, den: int) -> Optional[float]:
    return None if den == 0 else 100.0 * num / den


def reliability_breakdown(rows: pd.DataFrame) -> Dict[str, Optional[float]]:
    n = len(rows)
    if n == 0:
        return {
            "Blocked%": None,
            "OpenHandsFailed%": None,
            "MetricsFailed%": None,
            "BehaviorRegressed%": None,
            "StructureNotImproved%": None,
            "BothFailed%": None,
            "OtherError%": None,
        }

    vc = rows["outcome_class"].fillna("").value_counts()

    def p(name: str) -> float:
        return 100.0 * int(vc.get(name, 0)) / n

    return {
        "Blocked%": p("blocked"),
        "OpenHandsFailed%": p("openhands_failed"),
        "MetricsFailed%": p("metrics_failed"),
        "BehaviorRegressed%": p("behavior_regressed"),
        "StructureNotImproved%": p("structure_not_improved"),
        "BothFailed%": p("both_failed"),
        "OtherError%": p("other_error"),
    }


def tokens_per_success(rows: pd.DataFrame) -> Optional[float]:
    success_rows = rows[rows["outcome_class"] == SUCCESS_OUTCOME]
    if success_rows.empty:
        return None
    total_tokens = pd.to_numeric(rows["total_llm_tokens"], errors="coerce").dropna().sum()
    if total_tokens <= 0:
        return None
    return float(total_tokens / len(success_rows))


def run_omnibus_glmm(df: pd.DataFrame, modes: List[str], r_script_path: Path) -> pd.DataFrame:
    slim = df.loc[:, ["repo", "cycle_id", "mode", "succ"]].copy()
    with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", delete=True) as tmp:
        slim.to_csv(tmp.name, index=False)
        proc = subprocess.run(
            ["Rscript", str(r_script_path), tmp.name, "omnibus", *modes],
            capture_output=True,
            text=True,
            check=False,
        )

    if proc.stderr.strip():
        print(proc.stderr.strip())

    if proc.returncode != 0:
        return pd.DataFrame(
            [
                {
                    "analysis": "omnibus",
                    "method": None,
                    "reference_mode": None,
                    "comparison_mode": None,
                    "mode_levels": ";".join(modes),
                    "n_mode": len(modes),
                    "n_obs": None,
                    "converged": None,
                    "singular": None,
                    "beta": None,
                    "se": None,
                    "z": None,
                    "wald_p_two_sided": None,
                    "lrt_p": None,
                    "odds_ratio": None,
                    "or_ci_lo_95": None,
                    "or_ci_hi_95": None,
                    "n_cycle": None,
                    "glmm_note": proc.stderr.strip() or proc.stdout.strip() or f"R exit code {proc.returncode}",
                }
            ]
        )

    out = pd.read_csv(pd.io.common.StringIO(proc.stdout))
    return out


def build_mode_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    modes = list(df["mode"].dropna().astype(str).sort_values().unique())

    cycle_mode = (
        df.groupby(["repo", "cycle_id", "mode"], dropna=False)["succ"]
        .mean()
        .reset_index(name="cycle_success_rate")
    )

    for mode_id in modes:
        sub = df[df["mode"] == mode_id].copy()
        succ_col = sub["succ"].fillna(False).astype(bool)
        success_rows = sub[sub["outcome_class"] == SUCCESS_OUTCOME].copy()

        macro_vals = cycle_mode.loc[cycle_mode["mode"] == mode_id, "cycle_success_rate"]
        macro_success_pct = None if macro_vals.empty else 100.0 * float(macro_vals.mean())

        row = {
            "mode": mode_id,
            "n_runs": int(len(sub)),
            "n_success": int(succ_col.sum()),
            "micro_success_pct": pct(int(succ_col.sum()), int(len(sub))),
            "macro_n_cycles": int(len(macro_vals)),
            "macro_success_pct": macro_success_pct,
            "all_runs_total_tokens_mean": mean_or_none(sub["total_llm_tokens"]),
            "all_runs_total_tokens_median": median_or_none(sub["total_llm_tokens"]),
            "success_total_tokens_mean": mean_or_none(success_rows["total_llm_tokens"]),
            "success_total_tokens_median": median_or_none(success_rows["total_llm_tokens"]),
            "success_delta_edges_mean": mean_or_none(success_rows["delta_edges"]),
            "success_delta_edges_median": median_or_none(success_rows["delta_edges"]),
            "success_delta_nodes_mean": mean_or_none(success_rows["delta_nodes"]),
            "success_delta_loc_mean": mean_or_none(success_rows["delta_loc"]),
            "tokens_per_success": tokens_per_success(sub),
        }
        row.update(reliability_breakdown(sub))
        rows.append(row)

    return pd.DataFrame(rows)


def build_project_mode_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    cycle_mode = (
        df.groupby(["repo", "cycle_id", "mode"], dropna=False)["succ"]
        .mean()
        .reset_index(name="cycle_success_rate")
    )

    for (repo, mode), sub in df.groupby(["repo", "mode"], dropna=False):
        succ_col = sub["succ"].fillna(False).astype(bool)
        success_rows = sub[sub["outcome_class"] == SUCCESS_OUTCOME].copy()
        macro_vals = cycle_mode.loc[
            (cycle_mode["repo"] == repo) & (cycle_mode["mode"] == mode),
            "cycle_success_rate",
        ]

        row = {
            "repo": repo,
            "mode": mode,
            "n_runs": int(len(sub)),
            "n_success": int(succ_col.sum()),
            "micro_success_pct": pct(int(succ_col.sum()), int(len(sub))),
            "macro_n_cycles": int(len(macro_vals)),
            "macro_success_pct": None if macro_vals.empty else 100.0 * float(macro_vals.mean()),
            "all_runs_total_tokens_mean": mean_or_none(sub["total_llm_tokens"]),
            "all_runs_total_tokens_median": median_or_none(sub["total_llm_tokens"]),
            "tokens_per_success": tokens_per_success(sub),
            "success_total_tokens_mean": mean_or_none(success_rows["total_llm_tokens"]),
            "success_total_tokens_std": std_or_none(success_rows["total_llm_tokens"]),
            "success_delta_edges_mean": mean_or_none(success_rows["delta_edges"]),
            "success_delta_edges_std": std_or_none(success_rows["delta_edges"]),
            "success_delta_edges_median": median_or_none(success_rows["delta_edges"]),
            "success_delta_nodes_mean": mean_or_none(success_rows["delta_nodes"]),
            "success_delta_nodes_std": std_or_none(success_rows["delta_nodes"]),
            "success_delta_loc_mean": mean_or_none(success_rows["delta_loc"]),
            "success_delta_loc_std": std_or_none(success_rows["delta_loc"]),
            "success_openhands_tokens_mean": mean_or_none(success_rows["openhands_total_tokens"]),
            "success_explain_tokens_mean": mean_or_none(success_rows["explain_total_tokens"]),
        }
        row.update(reliability_breakdown(sub))
        rows.append(row)

    return pd.DataFrame(rows)


def build_cycle_mode_summary(df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        df.groupby(["repo", "cycle_id", "cycle_size", "mode"], dropna=False)
        .agg(
            n_runs=("succ", "size"),
            n_success=("succ", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
            success_rate=("succ", lambda s: float(pd.Series(s).fillna(False).astype(bool).mean())),
            mean_total_tokens=("total_llm_tokens", lambda s: pd.to_numeric(s, errors="coerce").mean()),
            median_total_tokens=("total_llm_tokens", lambda s: pd.to_numeric(s, errors="coerce").median()),
        )
        .reset_index()
    )
    agg["success_pct"] = 100.0 * agg["success_rate"]
    return agg


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize all modes from all_runs.csv.")
    ap.add_argument("--input", required=True, help="Path to all_runs.csv")
    ap.add_argument("--outdir", required=True)
    ap.add_argument(
        "--with-omnibus-glmm",
        action="store_true",
        help="Also run omnibus GLMM across all modes",
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
    df["outcome_class"] = df["outcome_class"].fillna("other_error")

    mode_summary = build_mode_summary(df)
    mode_summary_path = outdir / "mode_summary.csv"
    mode_summary.to_csv(mode_summary_path, index=False)
    print(f"Wrote: {mode_summary_path}", file=sys.stderr)

    project_summary = build_project_mode_summary(df)
    project_summary_path = outdir / "project_mode_summary.csv"
    project_summary.to_csv(project_summary_path, index=False)
    print(f"Wrote: {project_summary_path}", file=sys.stderr)

    cycle_mode_summary = build_cycle_mode_summary(df)
    cycle_mode_summary_path = outdir / "cycle_mode_summary.csv"
    cycle_mode_summary.to_csv(cycle_mode_summary_path, index=False)
    print(f"Wrote: {cycle_mode_summary_path}", file=sys.stderr)

    if args.with_omnibus_glmm:
        modes = list(df["mode"].dropna().astype(str).sort_values().unique())
        r_script = Path(__file__).resolve().parent / "glmm_cycle_mode_lme4.R"
        omnibus = run_omnibus_glmm(df, modes, r_script)
        omnibus_path = outdir / "omnibus_glmm.csv"
        omnibus.to_csv(omnibus_path, index=False)
        print(f"Wrote: {omnibus_path}", file=sys.stderr)


if __name__ == "__main__":
    import sys
    main()