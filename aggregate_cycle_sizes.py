#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Tuple, Dict, Any

def parse_repos_file(path: str) -> List[Tuple[str, str]]:
    """
    Parse repos.txt lines formatted like:
        repo_name  main_branch  [rest...]
    Ignores blank lines and comments (# ...).
    Returns list of (repo_name, main_branch).
    """
    repos: List[Tuple[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 2:
                raise ValueError(f"{path}:{i}: expected at least 2 columns (repo, main_branch); got: {line!r}")
            repos.append((parts[0], parts[1]))
    if not repos:
        raise ValueError(f"{path}: no repositories found")
    return repos

def load_json(p: Path) -> Dict[str, Any]:
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Missing file: {p}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {p}: {e}")

def extract_rep_cycle_lengths(data: Dict[str, Any], path: Path) -> List[int]:
    """
    Strictly extract representative cycle lengths.
    Errors if none found or malformed.
    """
    sccs = data.get("sccs")
    if not isinstance(sccs, list):
        raise ValueError(f"{path}: missing or invalid 'sccs' list")

    lengths: List[int] = []
    for scc in sccs:
        reps = scc.get("representative_cycles")
        if reps is None:
            # treat as an error: strict mode requires representative cycles
            raise ValueError(f"{path}: 'representative_cycles' missing in at least one SCC")
        if not isinstance(reps, list):
            raise ValueError(f"{path}: 'representative_cycles' must be a list")
        for rc in reps:
            ln = rc.get("length")
            if isinstance(ln, int):
                lengths.append(ln)
            else:
                raise ValueError(f"{path}: representative cycle missing integer 'length'")

    if len(lengths) == 0:
        # strict: consider this a pipeline failure (no reps extracted)
        raise ValueError(f"{path}: no representative cycle lengths found")
    return lengths

def aggregate(repos_file: str, results_root: str, output_json: str) -> Dict[str, Any]:
    repos = parse_repos_file(repos_file)
    results_root = results_root.rstrip("/\\")
    errors: List[str] = []

    overall: Counter[int] = Counter()
    per_repo: Dict[str, Dict[str, Any]] = {}
    per_size_repo_counts: Dict[int, Counter[str]] = defaultdict(Counter)

    for repo_name, main_branch in repos:
        mc_path = Path(results_root) / repo_name / main_branch / "ATD_identification" / "module_cycles.json"
        try:
            data = load_json(mc_path)
            lengths = extract_rep_cycle_lengths(data, mc_path)
            cnt = Counter(lengths)
            per_repo[repo_name] = {
                "branch": main_branch,
                "total_cycles": sum(cnt.values()),
                "by_cycle_size": {str(k): v for k, v in sorted(cnt.items())},
                "source_mode": "representative_cycles_only",
            }
            overall.update(cnt)
            for size, n in cnt.items():
                per_size_repo_counts[size][repo_name] += n
        except Exception as e:
            errors.append(str(e))

    if errors:
        # Report *all* problems and exit non-zero
        sys.stderr.write("\nERROR: One or more repositories failed strict checks:\n")
        for msg in errors:
            sys.stderr.write(f"  - {msg}\n")
        sys.exit(2)

    by_cycle_size: Dict[str, Dict[str, Any]] = {}
    for size, total in sorted(overall.items()):
        repo_list = [{"repo": r, "count": c} for r, c in per_size_repo_counts[size].most_common()]
        by_cycle_size[str(size)] = {"count": total, "repos": repo_list}

    out = {
        "summary": {
            "total_repos_listed": len(repos),
            "repos_with_data": len(per_repo),   # equal to total_repos_listed in strict success
            "total_cycles_counted": int(sum(overall.values())),
            "mode": "representative_cycles_only",
        },
        "by_cycle_size": by_cycle_size,
        "per_repo": per_repo,
        "meta": {
            "repos_file": os.path.abspath(repos_file),
            "results_root": os.path.abspath(results_root),
            "note": "Strict mode: fails if representative cycles are missing/empty/malformed.",
        },
    }

    os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out

def main():
    ap = argparse.ArgumentParser(
        description="Aggregate representative cycle sizes across repos (STRICT: fails if reps missing/empty)."
    )
    ap.add_argument("--repos-file", required=True, help="Path to repos.txt (format: repo_name main_branch ...)")
    ap.add_argument("--results-root", default="results", help="Root directory that contains per-repo outputs (default: results)")
    ap.add_argument("--output", default="cycle_sizes_aggregate.json", help="Where to write the aggregated JSON")
    args = ap.parse_args()

    _ = aggregate(args.repos_file, args.results_root, args.output)

if __name__ == "__main__":
    main()
