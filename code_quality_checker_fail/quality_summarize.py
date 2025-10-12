#!/usr/bin/env python3
# Usage:
#   python quality_summarize.py <OUT_ROOT> <REPO_NAME> <BASELINE_LABEL> <POST_LABEL> <OUT_JSON>
import csv, json, re, sys, xml.etree.ElementTree as ET
from pathlib import Path

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
    try: return len(json.loads(data))
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

# ---- PyExamine parsing -------------------------------------------------------
def pyexamine_summary(folder: Path):
    """Return {"total": int, "by_group": {"code": n, "structural": m, "architectural": k}}.
       Accepts CSV or text summary; robust to missing files."""
    csv_p = folder / "pyexamine.csv"
    txt_p = folder / "pyexamine.txt"
    total = 0
    by_group = {"code": 0, "structural": 0, "architectural": 0}

    if csv_p.exists():
        try:
            with csv_p.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = [h.lower() for h in reader.fieldnames or []]
                # try to identify a "category"/"type" column
                key = None
                for cand in ("category","type","group"):
                    if cand in headers: key = cand; break
                for row in reader:
                    total += 1
                    if key:
                        g = (row.get(key,"") or "").strip().lower()
                        if "structural" in g: by_group["structural"] += 1
                        elif "architect" in g: by_group["architectural"] += 1
                        elif "code" in g: by_group["code"] += 1
        except Exception:
            pass

    if total == 0 and txt_p.exists():
        txt = txt_p.read_text(encoding="utf-8", errors="ignore")
        # parse summary lines shown in docs
        m1 = re.search(r"Total\s+Structural\s+Smells:\s+(\d+)", txt, re.I)
        m2 = re.search(r"Total\s+Code\s+Smells:\s+(\d+)", txt, re.I)
        m3 = re.search(r"Total\s+Architectural\s+Smells:\s+(\d+)", txt, re.I)
        if m1: by_group["structural"] = int(m1.group(1))
        if m2: by_group["code"] = int(m2.group(1))
        if m3: by_group["architectural"] = int(m3.group(1))
        total = sum(by_group.values())

    # If still nothing, leave zeros
    return {"total": total, "by_group": by_group}

def collect(folder: Path):
    return {
        "pytest": junit_counts(folder/"pytest.xml"),
        "coverage": {"line_percent": coverage_percent(folder/"coverage.xml")},
        "ruff": {"issues": ruff_issues(folder/"ruff.json")},
        "mypy": {"errors": mypy_errors(folder)},
        "radon_cc": radon_complexity_counts(folder/"radon_cc.json"),
        "radon_mi": radon_mi_stats(folder/"radon_mi.json"),
        "vulture": {"suspects": vulture_suspects(folder/"vulture.txt")},
        "bandit": bandit_counts(folder/"bandit.json"),
        "pip_audit": pip_audit_counts(folder/"pip_audit.json"),
        "pyexamine": pyexamine_summary(folder),
    }

def deltas(a, b):
    def d(x, y):
        if x is None or y is None: return None
        return y - x
    # radon_cc per-rank delta (optional but handy)
    def radon_cc_delta(a_cc, b_cc):
        ranks = set(a_cc["by_rank"]) | set(b_cc["by_rank"])
        return {
            "total": d(a_cc["total"], b_cc["total"]),
            "by_rank": {r: (b_cc["by_rank"].get(r,0) - a_cc["by_rank"].get(r,0)) for r in ranks},
        }
    return {
        "pytest": {
            "tests":    d(a["pytest"]["tests"],    b["pytest"]["tests"]),
            "failures": d(a["pytest"]["failures"], b["pytest"]["failures"]),
            "errors":   d(a["pytest"]["errors"],   b["pytest"]["errors"]),
            "skipped":  d(a["pytest"]["skipped"],  b["pytest"]["skipped"]),
        },
        "coverage": {"line_percent": d(a["coverage"]["line_percent"], b["coverage"]["line_percent"])},
        "ruff":     {"issues": d(a["ruff"]["issues"], b["ruff"]["issues"])},
        "mypy":     {"errors": d(a["mypy"]["errors"], b["mypy"]["errors"])},
        "radon_cc": radon_cc_delta(a["radon_cc"], b["radon_cc"]),
        "radon_mi": {
            "avg":   d(a["radon_mi"]["avg"],   b["radon_mi"]["avg"]),
            "worst": d(a["radon_mi"]["worst"], b["radon_mi"]["worst"]),
        },
        "vulture":  {"suspects": d(a["vulture"]["suspects"], b["vulture"]["suspects"])},
        "bandit":   {
            "high":   d(a["bandit"]["high"],   b["bandit"]["high"]),
            "medium": d(a["bandit"]["medium"], b["bandit"]["medium"]),
            "low":    d(a["bandit"]["low"],    b["bandit"]["low"]),
            "total":  d(a["bandit"]["total"],  b["bandit"]["total"]),
        },
        "pip_audit": {"vulnerable_deps": d(a["pip_audit"]["vulnerable_deps"], b["pip_audit"]["vulnerable_deps"])},
        "pyexamine": {
            "total": d(a["pyexamine"]["total"], b["pyexamine"]["total"]),
            "by_group": {
                k: (b["pyexamine"]["by_group"].get(k,0) - a["pyexamine"]["by_group"].get(k,0))
                for k in set(a["pyexamine"]["by_group"]) | set(b["pyexamine"]["by_group"])
            }
        },
    }

if __name__ == "__main__":
    if len(sys.argv) != 6:
        print("Usage: python quality_summarize.py <OUT_ROOT> <REPO_NAME> <BASELINE_LABEL> <POST_LABEL> <OUT_JSON>", file=sys.stderr)
        sys.exit(2)
    out_root, repo, base_label, post_label, out_json = sys.argv[1:]
    base_dir = Path(out_root) / repo / base_label
    post_dir = Path(out_root) / repo / post_label
    a = collect(base_dir); b = collect(post_dir)
    report = {"meta": {
                "out_root": str(Path(out_root).resolve()),
                "repo": repo,
                "baseline_label": base_label,
                "post_label": post_label,
              },
              "baseline": a, "post": b, "deltas": deltas(a, b)}
    out_path = Path(out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
