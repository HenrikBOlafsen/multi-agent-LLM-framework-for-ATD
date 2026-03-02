#!/usr/bin/env python3
# code_quality_checker/quality_single_summary_csharp.py
#
# Minimal summary for C#/.NET repos, aligned with the Python schema style.
#
# Aggregates:
# - TRX results (dotnet test)
# - dotnet_test exit code
# - A Ruff-like lint count from SARIF (Roslyn /errorlog SARIF):
#     dotnet_lint.issues = count of *unsuppressed* SARIF results with level:
#         error | warning | note
#       plus results with missing/unknown level (counted as issues for safety)
#
# This produces a monotonic "up is worse, down is better" metric.
#
# Usage:
#   python quality_single_summary_csharp.py <METRICS_DIR> <OUT_JSON> [--with-provenance]
#
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, List, Optional, Dict


def _safe_strip(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _safe_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _read_int(p: Path) -> Optional[int]:
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# -------------------- TRX aggregation --------------------

def find_all_trx(metrics_dir: Path) -> List[Path]:
    trx_files = sorted(metrics_dir.glob("test_results/**/*.trx"))
    if not trx_files:
        trx_files = sorted(metrics_dir.glob("test_results/*.trx"))
    seen = set()
    out: List[Path] = []
    for p in trx_files:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def parse_trx_counts(trx_path: Path) -> Dict[str, int]:
    if trx_path is None or not trx_path.exists():
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    root = ET.parse(trx_path).getroot()
    counters = root.find(".//{*}ResultSummary/{*}Counters") or root.find(".//Counters")
    if counters is None:
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    def get_int(name: str) -> int:
        v = counters.attrib.get(name)
        try:
            return int(v) if v is not None else 0
        except Exception:
            return 0

    total = get_int("total")
    executed = get_int("executed")
    failed = get_int("failed")
    error = get_int("error")
    timeout = get_int("timeout")
    aborted = get_int("aborted")
    not_executed = get_int("notExecuted")
    not_runnable = get_int("notRunnable")

    errors = error + timeout + aborted
    skipped = not_executed + not_runnable
    if skipped == 0 and total > 0 and executed >= 0:
        delta = total - executed
        if delta > 0:
            skipped = delta

    return {"tests": total, "failures": failed, "errors": errors, "skipped": skipped}


def aggregate_trx_counts(trx_files: List[Path]) -> Dict[str, int]:
    agg = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for trx in trx_files:
        c = parse_trx_counts(trx)
        agg["tests"] += int(c.get("tests", 0))
        agg["failures"] += int(c.get("failures", 0))
        agg["errors"] += int(c.get("errors", 0))
        agg["skipped"] += int(c.get("skipped", 0))
    return agg


# -------------------- SARIF -> dotnet_lint.issues --------------------

_ALLOWED_LEVELS = {"error", "warning", "note"}
# We treat missing or unknown levels as issues (safer monotonic metric).


def find_all_sarif(metrics_dir: Path) -> List[Path]:
    sarif_files = sorted(metrics_dir.glob("sarif/**/*.sarif"))
    if not sarif_files:
        sarif_files = sorted(metrics_dir.glob("sarif/*.sarif"))

    seen = set()
    out: List[Path] = []
    for p in sarif_files:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def _iter_sarif_results(doc: dict) -> Iterable[dict]:
    if not isinstance(doc, dict):
        return
    runs = doc.get("runs", [])
    if not isinstance(runs, list):
        return
    for run in runs:
        if not isinstance(run, dict):
            continue
        results = run.get("results", [])
        if not isinstance(results, list):
            continue
        for r in results:
            if isinstance(r, dict):
                yield r


def _level(result: dict) -> str:
    lvl = result.get("level")
    if isinstance(lvl, str) and lvl.strip():
        return lvl.strip().lower()
    return ""


def _is_suppressed(result: dict) -> bool:
    # SARIF suppressionStates being non-empty indicates suppression.
    ss = result.get("suppressionStates")
    return isinstance(ss, list) and len(ss) > 0


def count_sarif_lint_issues(sarif_files: List[Path]) -> int:
    """
    Ruff-like metric:
      issues = count of unsuppressed SARIF results with level in {error, warning, note}
               plus unsuppressed results with missing/unknown level.
    """
    total = 0

    for sp in sarif_files:
        doc = _read_json(sp)
        if not doc:
            continue

        for r in _iter_sarif_results(doc):
            if _is_suppressed(r):
                continue

            lvl = _level(r)
            if not lvl:
                # missing level -> count as issue
                total += 1
                continue

            if lvl in _ALLOWED_LEVELS:
                total += 1
            else:
                # unknown/nonstandard level -> count as issue (safer)
                # (This also intentionally excludes "none"/"info" only when they are standard;
                #  if a producer uses a different token, we still count it.)
                if lvl not in {"none", "info", "information"}:
                    total += 1

    return total


# -------------------- Collector --------------------

def collect(metrics_dir: Path, with_prov: bool) -> dict:
    metrics_dir = Path(metrics_dir)

    trx_files = find_all_trx(metrics_dir)
    dotnet_test = aggregate_trx_counts(trx_files) if trx_files else {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    dotnet_test_exit_code = _read_int(metrics_dir / "dotnet_test_exit_code.txt")

    sarif_files = find_all_sarif(metrics_dir)
    lint_issues = count_sarif_lint_issues(sarif_files) if sarif_files else 0

    data = {
        "schema_version": 8,
        "language": "csharp",

        "dotnet_test": dotnet_test,
        "dotnet_test_exit_code": dotnet_test_exit_code,

        "dotnet_lint": {"issues": int(lint_issues)},
    }

    if with_prov:
        data["provenance"] = {
            "run_started_utc": _safe_strip(metrics_dir / "run_started_utc.txt"),
            "git_sha": _safe_strip(metrics_dir / "git_sha.txt"),
            "git_branch": _safe_strip(metrics_dir / "git_branch.txt"),
            "dotnet_info": _safe_text(metrics_dir / "dotnet_info.txt"),
            "test_strategy": _safe_strip(metrics_dir / "test_strategy.txt"),
            "test_target": _safe_strip(metrics_dir / "test_target.txt"),
            "test_workdir": _safe_strip(metrics_dir / "test_workdir.txt"),
            "trx_files_count": len(trx_files),
            "sarif_files_count": len(sarif_files),
        }

    return data


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: python quality_single_summary_csharp.py <METRICS_DIR> <OUT_JSON> [--with-provenance]",
            file=sys.stderr,
        )
        return 2

    metrics_dir = Path(sys.argv[1])
    out_json = Path(sys.argv[2])
    with_prov = ("--with-provenance" in sys.argv[3:])

    out_json.parent.mkdir(parents=True, exist_ok=True)
    report = collect(metrics_dir, with_prov)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())