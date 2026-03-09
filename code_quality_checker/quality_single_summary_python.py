#!/usr/bin/env python3
#
# Usage:
#   python quality_single_summary_python.py <METRICS_DIR> <OUT_JSON>
# Example:
#   python quality_single_summary_python.py results/kombu/main/code_quality_checks metrics.json

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_text(p):
    p = Path(p)
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


def read_json(p):
    p = Path(p)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# -------------------- Pytest / Trial / Coverage --------------------


def junit_counts(p):
    p = Path(p)
    if not p.exists():
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    try:
        root = ET.parse(p).getroot()
    except Exception:
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    suites = root.findall(".//testsuite") if root.tag != "testsuite" else [root]
    t = f = e = sk = 0
    for s in suites:
        t += int(s.attrib.get("tests", 0))
        f += int(s.attrib.get("failures", 0))
        e += int(s.attrib.get("errors", 0))
        sk += int(s.attrib.get("skipped", 0))
    return {"tests": t, "failures": f, "errors": e, "skipped": sk}


def trial_counts(p):
    """
    Parse Twisted Trial summary output from trial_full.log.

    Example endings:

        Ran 11470 tests in 263.279s

        PASSED (skips=649, successes=10821)

    Or:

        FAILED (failures=2, errors=1, skips=3, successes=100)
    """
    txt = read_text(p)
    if not txt:
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    tests = 0
    m = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+", txt)
    if m:
        try:
            tests = int(m.group(1))
        except Exception:
            tests = 0

    summary_matches = re.findall(
        r"^(PASSED|FAILED)\s*\(([^)]*)\)\s*$",
        txt,
        flags=re.MULTILINE,
    )
    if not summary_matches:
        return {"tests": tests, "failures": 0, "errors": 0, "skipped": 0}

    _status, payload = summary_matches[-1]

    counts = {}
    for key, value in re.findall(r"([A-Za-z_]+)\s*=\s*(\d+)", payload):
        counts[key.strip().lower()] = int(value)

    skipped = counts.get("skips", counts.get("skipped", 0))
    failures = counts.get("failures", counts.get("failure", 0))
    errors = counts.get("errors", counts.get("error", 0))

    if tests == 0:
        tests = (
            counts.get("successes", 0)
            + skipped
            + failures
            + errors
            + counts.get("expectedfailures", 0)
            + counts.get("unexpectedsuccesses", 0)
        )

    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def test_counts(folder: Path):
    folder = Path(folder)

    pytest_xml = folder / "pytest.xml"
    if pytest_xml.exists():
        return junit_counts(pytest_xml)

    trial_log = folder / "trial_full.log"
    if trial_log.exists():
        return trial_counts(trial_log)

    return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}


def coverage_percent(p):
    p = Path(p)
    if not p.exists():
        return None

    try:
        root = ET.parse(p).getroot()
    except Exception:
        return None

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
        return len(obj) if isinstance(obj, list) else 0
    except Exception:
        return sum(1 for _ in data.splitlines() if _)


def radon_complexity_counts(p):
    obj = read_json(p)
    total = 0
    by_rank = {}

    if not obj:
        return {"total": 0, "by_rank": {}}

    if isinstance(obj, dict):
        items = list(obj.items())
    elif isinstance(obj, list):
        items = [("<unknown>", obj)]
    else:
        return {"total": 0, "by_rank": {}}

    for _fname, entries in items:
        if isinstance(entries, dict):
            entries = (
                entries.get("functions")
                or entries.get("results")
                or entries.get("blocks")
                or []
            )
        if not isinstance(entries, list):
            continue

        for e in entries:
            total += 1
            rank = "?"
            if isinstance(e, dict):
                rank = e.get("rank") or e.get("complexity", {}).get("rank") or "?"
            by_rank[rank] = by_rank.get(rank, 0) + 1

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

    return {
        "avg": round(sum(mis) / len(mis), 2),
        "worst": round(min(mis), 2),
        "files": len(mis),
    }


def vulture_summary(p):
    """
    Parse vulture.txt lines like:

        path/to/file.py:123: unused variable 'x' (100% confidence)
    """
    txt = read_text(p)
    if not txt:
        return {
            "suspects": 0,
            "by_confidence": {"60": 0, "90": 0, "100": 0},
        }

    lines = [line.strip() for line in txt.splitlines() if line.strip()]
    suspect_lines = [line for line in lines if re.search(r"^.+:\d+:\s+", line)]

    by_confidence = {"60": 0, "90": 0, "100": 0}
    for line in suspect_lines:
        m = re.search(r"\((\d+)% confidence\)\s*$", line)
        if not m:
            continue
        conf = m.group(1)
        by_confidence[conf] = by_confidence.get(conf, 0) + 1

    return {
        "suspects": len(suspect_lines),
        "by_confidence": by_confidence,
    }


# -------------------- Collector --------------------


def collect(folder: Path):
    folder = Path(folder)

    return {
        "schema_version": 1,
        "language": "python",
        "pytest": test_counts(folder),
        "coverage": {"line_percent": coverage_percent(folder / "coverage.xml")},
        "ruff": {"issues": ruff_issues(folder / "ruff.json")},
        "radon_cc": radon_complexity_counts(folder / "radon_cc.json"),
        "radon_mi": radon_mi_stats(folder / "radon_mi.json"),
        "vulture": vulture_summary(folder / "vulture.txt"),
        "dotnet_test": None,
    }


# -------------------- CLI --------------------


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python quality_single_summary_python.py <METRICS_DIR> <OUT_JSON>",
            file=sys.stderr,
        )
        sys.exit(2)

    metrics_dir = Path(sys.argv[1])
    out_json = Path(sys.argv[2])

    out_json.parent.mkdir(parents=True, exist_ok=True)
    report = collect(metrics_dir)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_json}")