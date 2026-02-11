#!/usr/bin/env python3
# quality_single_summary_csharp.py
#
# Super-basic TRX aggregation:
# - aggregates *all* TRX files found under test_results/
# - no framework filtering and no per-TFM breakdown
#
# Usage:
#   python quality_single_summary_csharp.py <METRICS_DIR> <OUT_JSON> [--with-provenance]

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List


def _safe_strip(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _safe_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def find_all_trx(metrics_dir: Path) -> List[Path]:
    trx_files = sorted(metrics_dir.glob("test_results/**/*.trx"))
    if not trx_files:
        trx_files = sorted(metrics_dir.glob("test_results/*.trx"))
    # de-dupe
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


def collect(metrics_dir: Path, with_prov: bool) -> dict:
    metrics_dir = Path(metrics_dir)

    trx_files = find_all_trx(metrics_dir)
    dotnet_test = aggregate_trx_counts(trx_files) if trx_files else {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    data = {
        "schema_version": 1,
        "language": "csharp",
        "dotnet_test": dotnet_test,
    }

    if with_prov:
        data["provenance"] = {
            "run_started_utc": _safe_strip(metrics_dir / "run_started_utc.txt"),
            "git_sha": _safe_strip(metrics_dir / "git_sha.txt"),
            "git_branch": _safe_strip(metrics_dir / "git_branch.txt"),
            "dotnet_info": _safe_text(metrics_dir / "dotnet_info.txt"),
            "test_strategy": _safe_strip(metrics_dir / "test_strategy.txt"),
            "trx_files_count": len(trx_files),
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
