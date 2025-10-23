#!/usr/bin/env python3
"""
rq_utils.py — shared helpers for RQ1/RQ2/RQ3 table generators.

Conventions / Paths (under each branch dir):
  ATD_identification/ATD_metrics.json
  ATD_identification/module_cycles.json
  code_quality_checks/metrics.json
  *.diff (optional, for patch statistics)
"""

from __future__ import annotations
import json, math, re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Iterable
from scipy.stats import wilcoxon, binomtest, spearmanr  # noqa: F401 (some used in scripts)

# ---------- constants ----------
ATD_DIR = "ATD_identification"
ATD_METRICS = f"{ATD_DIR}/ATD_metrics.json"
ATD_MODULE_CYCLES = f"{ATD_DIR}/module_cycles.json"
CQ_METRICS = "code_quality_checks/metrics.json"

# ---------- basic IO ----------
def read_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def read_repos_file(path: Path) -> List[Tuple[str, str, str]]:
    """Return list of (repo, baseline_branch, src_rel)."""
    repos = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        repo = parts[0]
        baseline = parts[1]
        src_rel = parts[2] if len(parts) >= 3 else ""
        repos.append((repo, baseline, src_rel))
    return repos

# ---------- shared helpers (moved from RQ scripts) ----------
def sanitize(s: str) -> str:
    """Mirror branch-name sanitization from the pipeline."""
    s = s.replace(" ", "-")
    s = re.sub(r"[^A-Za-z0-9._/-]", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-/")
    return s

def branch_for(exp_label: str, cycle_id: str) -> str:
    """Branch naming used by the pipeline for LLM runs."""
    return sanitize(f"cycle-fix-{exp_label}-{cycle_id}")

def parse_cycles(cycles_file: Path) -> Dict[Tuple[str, str], List[str]]:
    """
    Returns {(repo, branch): [cycle_id, ...]} from cycles_to_analyze.txt
    (ignores comments and blank lines)
    """
    out: Dict[Tuple[str, str], List[str]] = {}
    for line in cycles_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        repo, branch, cid = parts[0], parts[1], parts[2]
        out.setdefault((repo, branch), []).append(cid)
    return out

def load_json_any(base: Path, candidates: List[str]) -> Optional[Dict[str, Any]]:
    """Try multiple relative paths under a base directory and return the first JSON found."""
    for rel in candidates:
        p = base / rel
        if p.exists():
            return read_json(p)
    return None

def mean_or_none(vals: List[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in vals if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))]
    return (sum(xs) / len(xs)) if xs else None

def safe_sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a) - float(b)

def cycle_size_from_baseline(base_repo_branch_dir: Path, cycle_id: str) -> Optional[int]:
    """
    Look up cycle length for a representative cycle in the baseline module_cycles.json.
    """
    mod = read_json(base_repo_branch_dir / ATD_MODULE_CYCLES)
    if not mod:
        return None
    for scc in mod.get("sccs", []):
        for cyc in scc.get("representative_cycles", []):
            if cyc.get("id") == cycle_id:
                if "length" in cyc and isinstance(cyc["length"], int):
                    return int(cyc["length"])
                nodes = cyc.get("nodes") or []
                return int(len(nodes))
    return None

# ---------- metrics parsing ----------
def get_tests_pass_percent(summary_json: Optional[Dict[str, Any]]) -> Optional[float]:
    if not summary_json:
        return None
    junit = summary_json.get("pytest") or {}
    tests    = junit.get("tests") or 0
    failures = junit.get("failures") or 0
    errors   = junit.get("errors") or 0
    skipped  = junit.get("skipped") or 0
    if tests <= 0:
        return None
    passed = max(0, tests - failures - errors - skipped)
    return round(100.0 * passed / tests, 2)

def get_scc_metrics(atd: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not atd:
        return {"scc_count": None, "max_scc_size": None, "avg_scc_size": None,
                "total_nodes_in_cyclic_sccs": None, "total_edges_in_cyclic_sccs": None,
                "total_loc_in_cyclic_sccs": None, "cycle_pressure_lb": None,
                "avg_density_directed": None, "avg_edge_surplus_lb": None}
    sccs = atd.get("sccs") or []
    avg_density = None
    avg_surplus = None
    if sccs:
        dens = [s.get("density_directed", 0.0) for s in sccs if isinstance(s, dict)]
        surp = [s.get("edge_surplus_lb", 0) for s in sccs if isinstance(s, dict)]
        if dens:
            avg_density = round(sum(dens) / len(dens), 4)
        if surp:
            avg_surplus = round(sum(surp) / len(surp), 2)
    return {
        "scc_count": atd.get("scc_count"),
        "max_scc_size": atd.get("max_scc_size"),
        "avg_scc_size": atd.get("avg_scc_size"),
        "total_nodes_in_cyclic_sccs": atd.get("total_nodes_in_cyclic_sccs"),
        "total_edges_in_cyclic_sccs": atd.get("total_edges_in_cyclic_sccs"),
        "total_loc_in_cyclic_sccs": atd.get("total_loc_in_cyclic_sccs"),
        "cycle_pressure_lb": atd.get("cycle_pressure_lb"),
        "avg_density_directed": avg_density,
        "avg_edge_surplus_lb": avg_surplus,
    }

def count_repr_cycles(module_cycles: Optional[Dict[str, Any]]) -> Optional[int]:
    if not module_cycles:
        return None
    sccs = module_cycles.get("sccs")
    arr: Iterable = sccs if isinstance(sccs, list) else (module_cycles if isinstance(module_cycles, list) else [])
    total = 0
    has_any = False
    for s in arr:
        if not isinstance(s, dict):
            continue
        reps = s.get("representative_cycles") or []
        if isinstance(reps, list):
            total += len(reps)
            has_any = True
    return (total if has_any else 0)

def extract_quality_metrics(j: Dict[str, Any]) -> Dict[str, Any]:
    """Subset used in RQ2."""
    junit = j.get("pytest") or {}
    tests    = junit.get("tests") or 0
    failures = junit.get("failures") or 0
    errors   = junit.get("errors") or 0
    skipped  = junit.get("skipped") or 0
    passed   = max(0, tests - failures - errors - skipped)
    pass_pct = (100.0 * passed / tests) if tests else 0.0

    ruff_issues = (j.get("ruff") or {}).get("issues")
    mi_avg = (j.get("radon_mi") or {}).get("avg")
    by_rank = ((j.get("radon_cc") or {}).get("by_rank") or {})
    d_rank_funcs = by_rank.get("D", 0)
    bandit_high = (j.get("bandit") or {}).get("high")
    px = j.get("pyexamine") or {}
    weighted_by_type = px.get("weighted_by_type") or {}
    arch_weighted = weighted_by_type.get("Architectural")

    return {
        "ruff_issues": ruff_issues,
        "mi_avg": mi_avg,
        "d_rank_funcs": d_rank_funcs,
        "pyexam_arch_weighted": arch_weighted,
        "test_pass_pct": round(pass_pct, 2),
        "bandit_high": bandit_high,
    }

def scan_patch_cost(branch_dir: Path) -> Tuple[Optional[int], Optional[int]]:
    """Estimate edit cost from any *.diff under this branch dir."""
    diffs = list(branch_dir.rglob("*.diff"))
    if not diffs:
        return None, None
    loc = 0
    files = 0
    for d in diffs:
        try:
            txt = d.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        files += len(re.findall(r"^diff --git a/.* b/.*$", txt, flags=re.MULTILINE))
        for line in txt.splitlines():
            if not line:
                continue
            if line.startswith(("+++", "---", "diff --git", "@@", "index ")):
                continue
            if line.startswith("+") or line.startswith("-"):
                loc += 1
    return (loc or None), (files or None)

# ---------- math / stats ----------
def is_num(x) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))

def pct_reduction(baseline: Optional[float], current: Optional[float]) -> Optional[float]:
    if not is_num(baseline) or not is_num(current) or baseline == 0:
        return None
    return 100.0 * (baseline - current) / abs(baseline)

def safe_pct_delta(old, new):
    if old is None or new is None:
        return None
    if old == 0:
        return None
    return 100.0 * (new - old) / abs(old)

def fmt(x, nd=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return ""
    return f"{x:.{nd}f}"

def cohen_h(p1: float, p2: float) -> float:
    """Cohen's h for proportions."""
    def _t(p): return 2.0 * math.asin(math.sqrt(max(0.0, min(1.0, p))))
    return _t(p1) - _t(p2)

def cliffs_delta(xs: List[float], ys: List[float]) -> float:
    """Cliff's delta (xs vs ys), in [-1, 1]."""
    nx, ny = len(xs), len(ys)
    if nx == 0 or ny == 0:
        return float("nan")
    gt = lt = 0
    for x in xs:
        for y in ys:
            if x > y: gt += 1
            elif x < y: lt += 1
    return (gt - lt) / (nx * ny)

def wilcoxon_paired(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) == len(ys) and len(xs) > 0:
        _, p = wilcoxon(xs, ys, zero_method="wilcox", correction=False, alternative="two-sided", mode="auto")
        return float(p)
    return None

def mcnemar_p(b: int, c: int) -> float:
    """McNemar with exact binomial on discordant pairs."""
    n = b + c
    if n == 0:
        return float("nan")
    res = binomtest(min(b, c), n=n, p=0.5, alternative="two-sided")
    return float(res.pvalue)
