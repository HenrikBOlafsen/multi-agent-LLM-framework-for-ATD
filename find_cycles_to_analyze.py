#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional, Iterable
from collections import defaultdict, deque, Counter

# ---------------------------
# Helpers
# ---------------------------

def parse_repos_file(path: Path) -> List[Tuple[str, str, str]]:
    """
    Parse repos.txt lines formatted like:
        <repo_name>  <base_branch>  [src_rel]
    Ignores blank lines and comments (# ...).
    Returns list of (repo, branch, src_rel).
    """
    rows: List[Tuple[str, str, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 2:
            raise ValueError(f"{path}:{i}: expected at least 2 columns (repo, branch); got: {line!r}")
        repo = parts[0]
        branch = parts[1]
        src_rel = parts[2] if len(parts) >= 3 else ""
        rows.append((repo, branch, src_rel))
    if not rows:
        raise ValueError(f"{path}: no repositories found")
    return rows


def load_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def iter_representative_cycles(module_cycles: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    sccs = module_cycles.get("sccs")
    if not isinstance(sccs, list):
        return []
    for scc in sccs:
        reps = scc.get("representative_cycles")
        if not isinstance(reps, list):
            continue
        for rc in reps:
            yield rc


def cycle_size(cycle: Dict[str, Any]) -> Optional[int]:
    ln = cycle.get("length")
    if isinstance(ln, int):
        return ln
    nodes = cycle.get("nodes")
    if isinstance(nodes, list):
        return len(nodes)
    return None


def cycle_id(cycle: Dict[str, Any]) -> Optional[str]:
    cid = cycle.get("id") or cycle.get("cycle_id")
    return str(cid) if cid is not None else None


# ---------------------------
# Selection core (per-size balancing)
# ---------------------------

def select_for_size_balanced(
    queues_by_repo: Dict[str, deque],
    max_per_size: int,
    repos_order: List[str],
    repos_rank: Dict[str, int],
    per_repo_selected_global: Counter,
    used_repos_global: set,
) -> List[Tuple[str, str]]:
    """
    Choose up to max_per_size cycles from per-repo queues for ONE cycle-size bucket,
    enforcing per-size spread:

      - If K >= N (K = repos with cycles for this size), pick N DISTINCT repos (cap 1 per repo),
        prioritizing repos with the fewest total selections so far (global fairness).
      - If K < N, first give one to every repo (order: fewest global so far),
        then distribute the remaining (N-K) fairly (fewest global; then fewest picked for this size; then repos_order).

    Returns list of (repo, cycle_id).
    """
    chosen: List[Tuple[str, str]] = []
    K = sum(1 for q in queues_by_repo.values() if q)
    if K == 0 or max_per_size <= 0:
        return chosen

    # Cap 1 per repo when enough repos exist to fill N distinct
    if K >= max_per_size:
        # one-per-repo selection: pick N repos by global fairness
        # we only need up to N repos; sort candidate repos by (global picks, repos_rank)
        candidates = [r for r in repos_order if queues_by_repo.get(r)]
        candidates.sort(key=lambda r: (per_repo_selected_global[r], repos_rank.get(r, 10**9), r))
        for repo in candidates[:max_per_size]:
            q = queues_by_repo.get(repo)
            if not q:
                continue
            cid = q.popleft()
            chosen.append((repo, cid))
            used_repos_global.add(repo)
            per_repo_selected_global[repo] += 1
        return chosen

    # K < N: give one to each repo first (fair order), then fill remainder fairly
    per_size_taken: Counter = Counter()

    # Phase A: one to each repo (if available), ordered by global fairness
    candidates = [r for r in repos_order if queues_by_repo.get(r)]
    candidates.sort(key=lambda r: (per_repo_selected_global[r], repos_rank.get(r, 10**9), r))
    for repo in candidates:
        if len(chosen) >= max_per_size:
            break
        q = queues_by_repo.get(repo)
        if not q:
            continue
        cid = q.popleft()
        chosen.append((repo, cid))
        used_repos_global.add(repo)
        per_repo_selected_global[repo] += 1
        per_size_taken[repo] += 1

    # Phase B: fairness fill for the remaining
    remaining = max_per_size - len(chosen)
    available = {r for r, q in queues_by_repo.items() if q}
    while remaining > 0 and available:
        # pick repo with (fewest global, then fewest this-size, then repos order)
        repo = min(
            available,
            key=lambda r: (per_repo_selected_global[r], per_size_taken[r], repos_rank.get(r, 10**9), r),
        )
        q = queues_by_repo.get(repo)
        if not q:
            available.discard(repo)
            continue
        cid = q.popleft()
        chosen.append((repo, cid))
        used_repos_global.add(repo)
        per_repo_selected_global[repo] += 1
        per_size_taken[repo] += 1
        remaining -= 1
        if not q:
            available.discard(repo)

    return chosen


# ---------------------------
# Main logic
# ---------------------------

def find_candidates_per_size(
    repos_file: Path,
    results_root: Path,
    min_size: Optional[int],
    max_size: Optional[int],
) -> Tuple[
    Dict[int, Dict[str, List[str]]],  # by_size: {size: {repo: [cycle_id,...]}}
    Dict[str, str],                   # repo -> branch
]:
    """
    Scan results/<repo>/<branch>/ATD_identification/module_cycles.json
    and collect representative cycles, grouped by size then by repo.
    """
    repos = parse_repos_file(repos_file)
    repo_to_branch = {r: b for (r, b, _s) in repos}

    by_size: Dict[int, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))

    for repo, branch, _src in repos:
        mc_path = results_root / repo / branch / "ATD_identification" / "module_cycles.json"
        data = load_json(mc_path)
        if not data:
            # Missing or invalid → skip; we just can't choose cycles from this repo.
            continue

        # Collect representative cycles for this repo
        cycles = list(iter_representative_cycles(data))
        for c in cycles:
            sz = cycle_size(c)
            cid = cycle_id(c)
            if sz is None or cid is None:
                continue
            if min_size is not None and sz < min_size:
                continue
            if max_size is not None and sz > max_size:
                continue
            by_size[sz][repo].append(cid)

    # Make order deterministic within each repo: dedupe + sort by cycle id
    for sz in list(by_size.keys()):
        for r in list(by_size[sz].keys()):
            by_size[sz][r] = sorted(set(by_size[sz][r]))

    return by_size, repo_to_branch


def main():
    ap = argparse.ArgumentParser(
        description="Autogenerate cycles_to_analyze.txt by sampling up to N cycles per cycle-size, "
                    "spreading selection across repos listed in repos.txt, with per-size fairness."
    )
    ap.add_argument("--repos-file", required=True, help="Path to repos.txt (repo  branch  [src_rel])")
    ap.add_argument("--results-root", default="results", help="Root dir containing results/<repo>/<branch>/ATD_identification/module_cycles.json")
    ap.add_argument("--max-per-size", type=int, required=True, help="Maximum number of cycles to sample per cycle-size")
    ap.add_argument("--output", default="cycles_to_analyze.txt", help="Where to write the output selection")
    ap.add_argument("--min-size", type=int, default=None, help="Optional minimum cycle size to consider")
    ap.add_argument("--max-size", type=int, default=None, help="Optional maximum cycle size to consider")
    ap.add_argument("--ascending-sizes", action="store_true", help="Pick sizes from smallest to largest (default: largest to smallest)")
    args = ap.parse_args()

    repos_file = Path(args.repos_file)
    results_root = Path(args.results_root)
    out_path = Path(args.output)

    by_size, repo_to_branch = find_candidates_per_size(
        repos_file=repos_file,
        results_root=results_root,
        min_size=args.min_size,
        max_size=args.max_size,
    )

    if not by_size:
        raise SystemExit("No cycle candidates found. Did you run the non-LLM pass to produce module_cycles.json?")

    # Preserve the order from repos.txt (deterministic tie-breaker)
    repos_order_list = [r for (r, _b, _s) in parse_repos_file(repos_file)]
    repos_rank = {r: i for i, r in enumerate(repos_order_list)}

    # Sizes order
    sizes = sorted(by_size.keys(), reverse=not args.ascending_sizes)

    used_repos_global: set = set()
    per_repo_selected_global = Counter()  # global tally across ALL sizes
    selection_lines: List[str] = []
    per_size_counts: Dict[int, int] = {}
    per_repo_selected_summary = Counter()

    for sz in sizes:
        # Build queues per repo for this size
        queues_by_repo: Dict[str, deque] = {}
        for repo in repos_order_list:
            cids = by_size.get(sz, {}).get(repo, [])
            if cids:
                queues_by_repo[repo] = deque(cids)

        if not queues_by_repo:
            continue

        chosen = select_for_size_balanced(
            queues_by_repo=queues_by_repo,
            max_per_size=args.max_per_size,
            repos_order=repos_order_list,
            repos_rank=repos_rank,
            per_repo_selected_global=per_repo_selected_global,
            used_repos_global=used_repos_global,
        )

        for repo, cid in chosen:
            branch = repo_to_branch.get(repo, "main")
            selection_lines.append(f"{repo} {branch} {cid}")
            per_size_counts[sz] = per_size_counts.get(sz, 0) + 1
            per_repo_selected_summary[repo] += 1

    # Write file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(selection_lines) + ("\n" if selection_lines else ""), encoding="utf-8")

    # Summary to stdout
    total = sum(per_size_counts.values())
    distinct_repos = sum(1 for r, n in per_repo_selected_global.items() if n > 0)
    print(f"Wrote {total} lines to {out_path}")
    print(f"Distinct repos covered: {distinct_repos}")
    if per_size_counts:
        print("Counts per cycle size:")
        for sz in sorted(per_size_counts):
            print(f"  size={sz}: {per_size_counts[sz]}")
    if per_repo_selected_summary:
        print("Selections per repo (global):")
        for repo in sorted(per_repo_selected_summary, key=lambda r: (per_repo_selected_summary[r], repos_rank.get(r, 10**9), r)):
            print(f"  {repo}: {per_repo_selected_summary[repo]}")

if __name__ == "__main__":
    main()
