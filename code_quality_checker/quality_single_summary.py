#!/usr/bin/env python3
# quality_single_summary.py
#
# Usage:
#   python quality_single_summary.py <METRICS_DIR> <OUT_JSON> [--with-provenance]
# Example:
#   python quality_single_summary.py results/kombu/main/code_quality_checks metrics.json

import json, re, sys, xml.etree.ElementTree as ET
from pathlib import Path
import csv


def read_text(p):
    p = Path(p)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def read_json(p):
    p = Path(p)
    if not p.exists():
        return None
    try:
        txt = p.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception:
        return None


# -------------------- Pytest / Coverage --------------------

def junit_counts(p):
    p = Path(p)
    if not p.exists():
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    root = ET.parse(p).getroot()
    suites = root.findall(".//testsuite") if root.tag != "testsuite" else [root]
    t = f = e = sk = 0
    for s in suites:
        t += int(s.attrib.get("tests", 0))
        f += int(s.attrib.get("failures", 0))
        e += int(s.attrib.get("errors", 0))
        sk += int(s.attrib.get("skipped", 0))
    return {"tests": t, "failures": f, "errors": e, "skipped": sk}


def coverage_percent(p):
    p = Path(p)
    if not p.exists():
        return None
    root = ET.parse(p).getroot()
    rate = root.attrib.get("line-rate")
    try:
        return round(float(rate) * 100, 2) if rate is not None else None
    except Exception:
        return None


# -------------------- Linters / Static --------------------

def ruff_issues(p):
    data = read_text(p)
    if not data:
        return 0
    try:
        obj = json.loads(data)
        if isinstance(obj, list):
            return len(obj)
        return 0
    except Exception:
        return sum(1 for _ in data.splitlines() if _)


def mypy_errors(folder: Path):
    p = Path(folder, "mypy.txt")
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8", errors="ignore")
    return len(re.findall(r":\d+:\d+:\s+error:", txt))


# --------- Radon (handle multiple JSON shapes robustly) ---------

def radon_complexity_counts(p):
    obj = read_json(p)
    total = 0
    by_rank = {}
    if not obj:
        return {"total": 0, "by_rank": {}}

    items = []
    if isinstance(obj, dict):
        items = list(obj.items())
    elif isinstance(obj, list):
        items = [("<unknown>", obj)]
    else:
        return {"total": 0, "by_rank": {}}

    for _fname, entries in items:
        if isinstance(entries, dict):
            entries = entries.get("functions") or entries.get("results") or entries.get("blocks") or []
        if not isinstance(entries, list):
            continue
        for e in entries:
            total += 1
            r = "?"
            if isinstance(e, dict):
                r = e.get("rank") or e.get("complexity", {}).get("rank") or "?"
            by_rank[r] = by_rank.get(r, 0) + 1

    return {"total": total, "by_rank": by_rank}


def radon_mi_stats(p):
    obj = read_json(p)
    if not obj:
        return {"avg": None, "worst": None, "files": 0}
    mis = []
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, dict) and "mi" in v:
                try:
                    mis.append(float(v["mi"]))
                except Exception:
                    pass
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict) and "mi" in v:
                try:
                    mis.append(float(v["mi"]))
                except Exception:
                    pass
    if not mis:
        return {"avg": None, "worst": None, "files": 0}
    return {"avg": round(sum(mis) / len(mis), 2), "worst": round(min(mis), 2), "files": len(mis)}


def bandit_counts(p):
    obj = read_json(p) or {}
    results = obj.get("results", []) if isinstance(obj, dict) else []
    high = sum(1 for r in results if (r.get("issue_severity", "") or "").lower() == "high")
    med = sum(1 for r in results if (r.get("issue_severity", "") or "").lower() == "medium")
    low = sum(1 for r in results if (r.get("issue_severity", "") or "").lower() == "low")
    return {"high": high, "medium": med, "low": low, "total": high + med + low}


def vulture_suspects(p):
    txt = read_text(p)
    if not txt:
        return 0
    return len(re.findall(r":\d+:\d+", txt))


def pip_audit_counts(p):
    obj = read_json(p) or {}
    vulns = obj.get("vulnerabilities", []) if isinstance(obj, dict) else []
    return {"vulnerable_deps": len(vulns) if isinstance(vulns, list) else None}


# -------------------- PyExamine (optional) --------------------

def pyexamine_summary(folder: Path):
    px = folder / "pyexamine"
    if not px.exists():
        return None

    csv_files = sorted(px.glob("code_quality_report_*.csv"))
    if not csv_files:
        single = px / "code_quality_report.csv"
        if single.exists():
            csv_files = [single]
    if not csv_files:
        return None

    type_buckets = ["Architectural", "Code", "Structural"]
    sev_buckets = ["High", "Medium", "Low"]

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
    by_type_severity = {t: {s: 0 for s in sev_buckets + ["Unspecified"]} for t in by_type.keys()}

    files_aggregated = 0

    for path in csv_files:
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
                type_col = headers.get("type")
                name_col = headers.get("name")
                sev_col = headers.get("severity")

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
            continue

    def weighted(sev_counts):
        return 3 * sev_counts.get("High", 0) + 1 * sev_counts.get("Medium", 0)

    per_type_weighted = {t: weighted(by_type_severity[t]) for t in by_type_severity}

    return {
        "total": total,
        "by_name": by_name,
        "by_type": by_type,
        "by_severity": by_severity,
        "by_type_severity": by_type_severity,
        "weighted_total": weighted(by_severity),
        "weighted_by_type": per_type_weighted,
        "files_aggregated": files_aggregated,
    }


# -------------------- Collector --------------------

def collect(folder: Path, with_prov: bool):
    folder = Path(folder)

    data = {
        "schema_version": 1,
        "language": "python",

        # Python tests
        "pytest": junit_counts(folder / "pytest.xml"),
        "coverage": {"line_percent": coverage_percent(folder / "coverage.xml")},

        # Python-only static analysis
        "ruff": {"issues": ruff_issues(folder / "ruff.json")},
        "mypy": {"errors": mypy_errors(folder)},
        "radon_cc": radon_complexity_counts(folder / "radon_cc.json"),
        "radon_mi": radon_mi_stats(folder / "radon_mi.json"),
        "vulture": {"suspects": vulture_suspects(folder / "vulture.txt")},
        "bandit": bandit_counts(folder / "bandit.json"),
        "pip_audit": pip_audit_counts(folder / "pip_audit.json"),
        "pyexamine": pyexamine_summary(folder),

        # Present for schema alignment; filled in C# summary instead
        "dotnet_test": None,
    }

    if with_prov:
        def safe_strip(p: Path):
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception:
                return ""

        def safe_text(p: Path):
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return ""

        data["provenance"] = {
            "run_started_utc": safe_strip(folder / "run_started_utc.txt"),
            "python_version": safe_strip(folder / "python_version.txt"),
            "git_sha": safe_strip(folder / "git_sha.txt"),
            "git_branch": safe_strip(folder / "git_branch.txt"),
            "uname": safe_strip(folder / "uname.txt"),
            "tool_versions": safe_text(folder / "tool_versions.txt"),
            "pip_freeze": safe_text(folder / "pip_freeze.txt"),
            "src_paths": safe_text(folder / "src_paths.txt").splitlines(),
        }

    return data


# -------------------- CLI --------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python quality_single_summary.py <METRICS_DIR> <OUT_JSON> [--with-provenance]", file=sys.stderr)
        sys.exit(2)

    metrics_dir = Path(sys.argv[1])
    out_json = Path(sys.argv[2])
    with_prov = ("--with-provenance" in sys.argv[3:])

    out_json.parent.mkdir(parents=True, exist_ok=True)
    report = collect(metrics_dir, with_prov)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_json}")
