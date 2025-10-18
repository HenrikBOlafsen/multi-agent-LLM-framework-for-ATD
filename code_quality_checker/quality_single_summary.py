#!/usr/bin/env python3
# Usage:
#   python quality_single_summary.py <METRICS_DIR> <OUT_JSON> [--with-provenance]
# Example:
#   python quality_single_summary.py results/kombu/main/code_quality_checks metrics.json

import json, re, sys, xml.etree.ElementTree as ET
from pathlib import Path
import csv, re

def read_text(p): return Path(p).read_text(encoding="utf-8") if Path(p).exists() else ""
def read_json(p):
    try:
        return json.loads(read_text(p)) if Path(p).exists() else None
    except Exception:
        return None

def junit_counts(p):
    if not Path(p).exists(): return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    root = ET.parse(p).getroot()
    suites = root.findall(".//testsuite") if root.tag != "testsuite" else [root]
    t=f=e=sk=0
    for s in suites:
        t  += int(s.attrib.get("tests", 0))
        f  += int(s.attrib.get("failures", 0))
        e  += int(s.attrib.get("errors", 0))
        sk += int(s.attrib.get("skipped", 0))
    return {"tests": t, "failures": f, "errors": e, "skipped": sk}

def coverage_percent(p):
    if not Path(p).exists(): return None
    root = ET.parse(p).getroot()
    rate = root.attrib.get("line-rate")
    try: return round(float(rate) * 100, 2) if rate is not None else None
    except: return None

def ruff_issues(p):
    data = read_text(p)
    if not data: return 0
    try: return len(json.loads(data))  # JSON array output
    except: return sum(1 for _ in data.splitlines() if _)

def mypy_errors(folder: Path):
    p = Path(folder, "mypy.txt")
    if not p.exists(): return None
    txt = p.read_text(encoding="utf-8")
    return len(re.findall(r":\d+:\d+:\s+error:", txt))

def radon_complexity_counts(p):
    obj = read_json(p) or {}
    total = 0; by_rank = {}
    for entries in obj.values():
        for e in entries:
            total += 1
            r = e.get("rank","?")
            by_rank[r] = by_rank.get(r, 0) + 1
    return {"total": total, "by_rank": by_rank}

def radon_mi_stats(p):
    obj = read_json(p) or {}
    mis = [v.get("mi") for v in obj.values() if isinstance(v, dict) and "mi" in v]
    if not mis: return {"avg": None, "worst": None, "files": 0}
    return {"avg": round(sum(mis)/len(mis),2), "worst": round(min(mis),2), "files": len(mis)}

def bandit_counts(p):
    obj = read_json(p) or {}
    results = obj.get("results", []) if isinstance(obj, dict) else []
    high = sum(1 for r in results if r.get("issue_severity","").lower()=="high")
    med  = sum(1 for r in results if r.get("issue_severity","").lower()=="medium")
    low  = sum(1 for r in results if r.get("issue_severity","").lower()=="low")
    return {"high": high, "medium": med, "low": low, "total": high+med+low}

def vulture_suspects(p):
    txt = read_text(p)
    if not txt: return 0
    return len(re.findall(r":\d+:\d+", txt))

def pip_audit_counts(p):
    obj = read_json(p) or {}
    vulns = obj.get("vulnerabilities", [])
    return {"vulnerable_deps": len(vulns)} if isinstance(vulns, list) else {"vulnerable_deps": None}



def pyexamine_summary(folder: Path):
    px = folder / "pyexamine"
    if not px.exists():
        return None

    # Support one or many outputs
    csv_files = sorted(px.glob("code_quality_report_*.csv"))
    if not csv_files:
        single = px / "code_quality_report.csv"
        if single.exists():
            csv_files = [single]
    if not csv_files:
        return None

    # Canonical buckets
    type_buckets = ["Architectural", "Code", "Structural"]
    sev_buckets  = ["High", "Medium", "Low"]
    def norm_type(s): 
        s = (s or "").strip()
        return s if s in type_buckets else "Unspecified"
    def norm_sev(s):
        s = (s or "").strip().capitalize()
        return s if s in sev_buckets else "Unspecified"

    total = 0
    by_name = {}
    by_type = {t: 0 for t in type_buckets + ["Unspecified"]}
    by_severity = {s: 0 for s in sev_buckets + ["Unspecified"]}
    # Type x Severity counts
    by_type_severity = {
        t: {s: 0 for s in sev_buckets + ["Unspecified"]}
        for t in by_type.keys()
    }

    files_aggregated = 0

    for path in csv_files:
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # case-insensitive header access
                headers = { (h or "").strip().lower(): h for h in (reader.fieldnames or []) }
                type_col = headers.get("type")         # "Type"
                name_col = headers.get("name")         # "Name"
                sev_col  = headers.get("severity")     # "Severity"

                for row in reader:
                    total += 1
                    typ = norm_type(row.get(type_col, "")) if type_col else "Unspecified"
                    sev = norm_sev(row.get(sev_col, "")) if sev_col else "Unspecified"
                    name = (row.get(name_col) or "unknown").strip() if name_col else "unknown"

                    by_type[typ] += 1
                    by_severity[sev] += 1
                    by_type_severity[typ][sev] += 1
                    by_name[name] = by_name.get(name, 0) + 1

            files_aggregated += 1
        except Exception:
            # ignore problematic files and continue
            continue

    def weighted(sev_counts):
        # 3*High + 1*Medium
        return 3*sev_counts.get("High", 0) + 1*sev_counts.get("Medium", 0)

    # Per-type weighted
    per_type_weighted = { t: weighted(by_type_severity[t]) for t in by_type_severity }

    return {
        "total": total,
        "by_name": by_name,                  # detailed, for drill-downs (don’t put in the paper table)
        "by_type": by_type,                  # Architectural / Code / Structural / Unspecified
        "by_severity": by_severity,          # High / Medium / Low / Unspecified
        "by_type_severity": by_type_severity,# matrix
        "weighted_total": weighted(by_severity),
        "weighted_by_type": per_type_weighted,
        "files_aggregated": files_aggregated
    }






def collect(folder: Path, with_prov: bool):
    data = {
        "pytest":     junit_counts(folder/"pytest.xml"),
        "coverage":   {"line_percent": coverage_percent(folder/"coverage.xml")},
        "ruff":       {"issues": ruff_issues(folder/"ruff.json")},
        "mypy":       {"errors": mypy_errors(folder)},
        "radon_cc":   radon_complexity_counts(folder/"radon_cc.json"),
        "radon_mi":   radon_mi_stats(folder/"radon_mi.json"),
        "vulture":    {"suspects": vulture_suspects(folder/"vulture.txt")},
        "bandit":     bandit_counts(folder/"bandit.json"),
        "pip_audit":  pip_audit_counts(folder/"pip_audit.json"),
        "pyexamine":  pyexamine_summary(folder),
    }
    if with_prov:
        def safe_strip(p: Path):
            try: return p.read_text(encoding="utf-8").strip()
            except Exception: return ""
        def safe_text(p: Path):
            try: return p.read_text(encoding="utf-8")
            except Exception: return ""
        data["provenance"] = {
            "run_started_utc": safe_strip(folder/"run_started_utc.txt"),
            "python_version":  safe_strip(folder/"python_version.txt"),
            "git_sha":         safe_strip(folder/"git_sha.txt"),
            "git_branch":      safe_strip(folder/"git_branch.txt"),
            "uname":           safe_strip(folder/"uname.txt"),
            "tool_versions":   safe_text(folder/"tool_versions.txt"),
            "pip_freeze":      safe_text(folder/"pip_freeze.txt"),
            "src_paths":       safe_text(folder/"src_paths.txt").splitlines(),
        }
    return data

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python quality_single_summary.py <METRICS_DIR> <OUT_JSON> [--with-provenance]", file=sys.stderr)
        sys.exit(2)

    metrics_dir = Path(sys.argv[1])
    out_json    = Path(sys.argv[2])
    with_prov   = ("--with-provenance" in sys.argv[3:])

    out_json.parent.mkdir(parents=True, exist_ok=True)
    report = collect(metrics_dir, with_prov)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_json}")
