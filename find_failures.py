#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# ---------- repos.txt parsing ----------
def read_repos_file(path: Path):
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 2:
            raise ValueError(f"{path}:{i}: expected 'repo branch [src]' but got: {line!r}")
        repo = parts[0]; branch = parts[1]; src = parts[2] if len(parts) >= 3 else ""
        rows.append((repo, branch, src))
    if not rows:
        raise ValueError(f"{path}: no repositories found")
    return rows

# ---------- io helpers ----------
def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def latest_log_path(oh_dir: Path) -> Optional[Path]:
    if not oh_dir.exists():
        return None
    logs = sorted(oh_dir.glob("run_*.log"))
    return logs[-1] if logs else None

# ---------- branch parsing (no legacy, no reruns) ----------
BRANCH_RE = re.compile(r"^cycle-fix-(?P<exp>.+)-(?P<cid>[^/]+)$")

def parse_llm_branch(name: str) -> Optional[Tuple[str, str]]:
    """Return (exp_label, cycle_id) from 'cycle-fix-<exp>-<cycle_id>'."""
    m = BRANCH_RE.match(name)
    if not m:
        return None
    return m.group("exp"), m.group("cid")

def condition_from_exp(exp_label: str) -> str:
    return "without" if exp_label.endswith("_without_explanation") else "with"

# ---------- classification ----------
def classify_outcome(explain_status: Optional[Dict[str, Any]], oh_status: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """
    outcome ∈ { pushed, explain_llm_error, openhands_llm_error, push_failed, no_changes,
                openhands_missing_status, incomplete_status, missing_both_status }
    returns (outcome, detail_reason)
    """
    if explain_status and explain_status.get("outcome") == "llm_error":
        return "explain_llm_error", (explain_status.get("reason") or "")
    if oh_status:
        out = oh_status.get("outcome"); reason = (oh_status.get("reason") or "")
        if out == "pushed":      return "pushed", ""
        if out == "no_changes":  return "no_changes", reason
        if out == "push_failed": return "push_failed", reason
        if out == "llm_error":   return "openhands_llm_error", reason
        if out == "started":     return "incomplete_status", reason or "wrapper_did_not_finalize"
        # Any other unexpected label → bucket as OH error (conservative)
        return "openhands_llm_error", reason
    if explain_status and explain_status.get("outcome") == "ok":
        return "openhands_missing_status", ""
    if not explain_status:
        return "missing_both_status", ""
    return "openhands_missing_status", ""

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(
        description="List failed/successful LLM runs for a single experiment label (branch-based storage only)."
    )
    ap.add_argument("--results-root", required=True)
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--experiment-id", required=True,
                    help="Base experiment label (e.g., expAA). Script also includes expAA_without_explanation automatically.")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--include-success", action="store_true", help="Also include successful runs (pushed)")
    args = ap.parse_args()

    results_root = Path(args.results_root)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    exp_with = args.experiment_id
    exp_without = f"{args.experiment_id}_without_explanation"
    allowed_experiments = {exp_with, exp_without}

    repos = read_repos_file(Path(args.repos_file))

    rows: List[Dict[str, Any]] = []
    summary: Dict[Tuple[str, str], int] = {}  # (condition, outcome) -> count

    for repo, _baseline_branch, _ in repos:
        repo_dir = results_root / repo
        if not repo_dir.exists():
            continue

        for branch_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
            parsed = parse_llm_branch(branch_dir.name)
            if not parsed:
                continue
            exp_label, cycle_id = parsed
            if exp_label not in allowed_experiments:
                continue

            condition = condition_from_exp(exp_label)

            explain_dir   = branch_dir / "explain_AS"
            openhands_dir = branch_dir / "openhands"

            exp_status = read_json(explain_dir / "status.json")
            oh_status  = read_json(openhands_dir / "status.json")

            outcome, detail = classify_outcome(exp_status, oh_status)
            if (outcome == "pushed") and not args.include_success:
                continue

            cyc_meta = read_json(branch_dir / "cycle_analyzed.json") or {}
            cycle_size = None
            cyc = cyc_meta.get("cycle")
            if isinstance(cyc, dict):
                if isinstance(cyc.get("length"), int):
                    cycle_size = cyc["length"]
                elif isinstance(cyc.get("nodes"), list):
                    cycle_size = len(cyc["nodes"])

            run_log = (oh_status or {}).get("run_log") or ""
            if not run_log:
                maybe = latest_log_path(openhands_dir)
                run_log = str(maybe) if maybe else ""

            rows.append({
                "repo": repo,
                "branch": branch_dir.name,
                "experiment": exp_label,
                "condition": condition,
                "cycle_id": cycle_id,
                "cycle_size": cycle_size,
                "outcome": outcome,
                "detail_reason": detail,
                "explain_status_path": str(explain_dir / "status.json") if (explain_dir / "status.json").exists() else "",
                "openhands_status_path": str(openhands_dir / "status.json") if (openhands_dir / "status.json").exists() else "",
                "cycle_analyzed_path": str(branch_dir / "cycle_analyzed.json") if (branch_dir / "cycle_analyzed.json").exists() else "",
                "run_log": run_log,
            })

            summary[(condition, outcome)] = summary.get((condition, outcome), 0) + 1

    # per-cycle CSV
    per_cycle_csv = outdir / "failures_per_cycle.csv"
    if rows:
        fields = [
            "repo","branch","experiment","condition",
            "cycle_id","cycle_size",
            "outcome","detail_reason",
            "explain_status_path","openhands_status_path","cycle_analyzed_path","run_log",
        ]
        with per_cycle_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})
        print(f"Wrote: {per_cycle_csv}")
    else:
        print("No runs found to report for experiment:", args.experiment_id)

    # summary CSV
    if summary:
        summary_csv = outdir / "failures_summary.csv"
        with summary_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["condition","reason","count"])
            w.writeheader()
            for (cond, reason), count in sorted(summary.items(), key=lambda kv: (kv[0][0], -kv[1])):
                w.writerow({"condition": cond, "reason": reason, "count": count})
        print(f"Wrote: {summary_csv}")

        print("Summary:")
        for (cond, reason), count in sorted(summary.items(), key=lambda kv: (kv[0][0], -kv[1])):
            print(f"  [{cond}] {reason}: {count}")

if __name__ == "__main__":
    main()
