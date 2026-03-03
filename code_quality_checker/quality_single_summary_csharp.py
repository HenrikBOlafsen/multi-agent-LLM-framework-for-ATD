#!/usr/bin/env python3
# code_quality_checker/quality_single_summary_csharp.py
#
# Aggregates (machine-readable):
# - TRX results (dotnet test)
# - dotnet_test exit code
# - "Ruff-like" lint count from SARIF produced via /errorlog (Roslyn analyzers)
# - "Radon-ish" complexity summary from Lizard CSV (optional)
#
# Usage:
#   python quality_single_summary_csharp.py <METRICS_DIR> <OUT_JSON> [--with-provenance]
#
from __future__ import annotations

import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 11

# Count unsuppressed WARNING/ERROR SARIF results as lint issues.
INCLUDE_LINT_LEVELS = {"warning", "error"}

# Radon-style thresholds (Radon D+E+F == CC >= 21, i.e. > 20)
CC_OVER_20_THRESHOLD = 20
CC_OVER_40_THRESHOLD = 40


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

    # Don't do `a or b` with Elements. An element with no children can be falsy.
    counters = root.find(".//{*}ResultSummary/{*}Counters")
    if counters is None:
        counters = root.find(".//Counters")
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


# -------------------- SARIF -> Ruff-like lint count --------------------

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


def count_lint_issues_from_sarif(sarif_paths: List[Path]) -> int:
    issues = 0
    for sp in sarif_paths:
        doc = _read_json(sp)
        if not doc:
            continue
        for r in _iter_sarif_results(doc):
            ss = r.get("suppressionStates")
            if isinstance(ss, list) and len(ss) > 0:
                continue
            lvl = r.get("level")
            lvl = lvl.strip().lower() if isinstance(lvl, str) else ""
            if lvl in INCLUDE_LINT_LEVELS:
                issues += 1
    return issues


# -------------------- Lizard (Radon-ish complexity) --------------------

def _p95_int(values: List[int]) -> Optional[int]:
    if not values:
        return None
    vs = sorted(values)
    idx = int(math.ceil(0.95 * len(vs))) - 1  # nearest-rank p95
    idx = max(0, min(idx, len(vs) - 1))
    return int(vs[idx])


def parse_lizard_complexity(metrics_dir: Path) -> Dict[str, Any]:
    """
    Reads CSV produced by:
        lizard --csv --languages csharp .
    Observed format (no header), first columns look like:
        CCN,NLOC,token,PARAM,length,"location@..@./path/file.cs","./path/file.cs",...
    We keep it simple:
      - CCN = column 0 (int)
      - file path = column 6 if present, else derive from the location column
      - cc_over_20 = count of functions with CCN > 20  (Radon D+E+F equivalent)
      - cc_over_40 = count of functions with CCN > 40  (Radon F equivalent)
    """
    csv_path = metrics_dir / "dotnet_complexity" / "lizard.csv"
    if not csv_path.exists():
        return {
            "cc_total": None,
            "cc_p95": None,
            "cc_over_20": 0,
            "cc_over_40": 0,
            "functions": 0,
            "files": 0,
            "csv_present": False,
        }

    cc_values: List[int] = []
    file_set: set[str] = set()
    over_20 = 0
    over_40 = 0

    try:
        with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue

                # CCN in column 0
                try:
                    ccn = int(str(row[0]).strip())
                except Exception:
                    # Skip header-ish / junk rows
                    continue

                cc_values.append(ccn)

                if ccn > CC_OVER_20_THRESHOLD:
                    over_20 += 1
                if ccn > CC_OVER_40_THRESHOLD:
                    over_40 += 1

                # File path usually in column 6
                file_path = ""
                if len(row) >= 7:
                    file_path = str(row[6]).strip().strip('"')
                if not file_path and len(row) >= 6:
                    # Fallback: location often contains ...@...@./path/file.cs
                    loc = str(row[5]).strip().strip('"')
                    parts = loc.split("@")
                    file_path = (parts[-1].strip() if parts else loc)

                if file_path:
                    file_set.add(file_path)
    except Exception:
        return {
            "cc_total": None,
            "cc_p95": None,
            "cc_over_20": 0,
            "cc_over_40": 0,
            "functions": 0,
            "files": 0,
            "csv_present": True,
        }

    if not cc_values:
        return {
            "cc_total": None,
            "cc_p95": None,
            "cc_over_20": 0,
            "cc_over_40": 0,
            "functions": 0,
            "files": int(len(file_set)),
            "csv_present": True,
        }

    return {
        "cc_total": int(sum(cc_values)),
        "cc_p95": _p95_int(cc_values),
        "cc_over_20": int(over_20),
        "cc_over_40": int(over_40),
        "functions": int(len(cc_values)),
        "files": int(len(file_set)),
        "csv_present": True,
    }


# -------------------- Collector --------------------

def collect(metrics_dir: Path, with_prov: bool) -> dict:
    metrics_dir = Path(metrics_dir)

    trx_files = find_all_trx(metrics_dir)
    dotnet_test = aggregate_trx_counts(trx_files) if trx_files else {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    dotnet_test_exit_code = _read_int(metrics_dir / "dotnet_test_exit_code.txt")

    sarif_files = find_all_sarif(metrics_dir)
    dotnet_lint = {"issues": count_lint_issues_from_sarif(sarif_files) if sarif_files else 0}

    dotnet_complexity = parse_lizard_complexity(metrics_dir)

    data = {
        "schema_version": SCHEMA_VERSION,
        "language": "csharp",
        "dotnet_test": dotnet_test,
        "dotnet_test_exit_code": dotnet_test_exit_code,
        "dotnet_lint": dotnet_lint,
        "dotnet_complexity": dotnet_complexity,
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
        print("Usage: python quality_single_summary_csharp.py <METRICS_DIR> <OUT_JSON> [--with-provenance]", file=sys.stderr)
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