#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set


# -------------------------
# Fixed, thesis-friendly knobs (NO FLAGS)
# -------------------------
ATTEMPTS_PER_SCC = 50000
MAX_CYCLES_PER_SCC = 200
SEED = 12345

# Simple + defendable:
# "We allow a file to appear in at most 2 selected cycles within the same repo,
# to reduce intra-repo dependence while keeping enough data."
MAX_NODE_USE_PER_REPO = 2


# -------------------------
# Small helpers
# -------------------------

def parse_repos_file(path: Path) -> List[Tuple[str, str, str, str]]:
    """
    repos.txt line:
      <repo_name> <base_branch> <entry> <language?>
    """
    rows: List[Tuple[str, str, str, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 3:
            raise ValueError(f"{path}:{i}: expected >=3 cols (repo, branch, entry)")
        repo, branch, entry = parts[0], parts[1], parts[2]
        lang = parts[3] if len(parts) >= 4 else "unknown"
        rows.append((repo, branch, entry, lang))
    return rows


def load_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def iter_catalog_cycles(catalog: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for scc in (catalog.get("sccs") or []):
        for cyc in (scc.get("cycles") or []):
            yield cyc


def cycle_size(cyc: Dict[str, Any]) -> Optional[int]:
    ln = cyc.get("length")
    if isinstance(ln, int):
        return ln
    nodes = cyc.get("nodes")
    if isinstance(nodes, list):
        return len(nodes)
    return None


def cycle_id(cyc: Dict[str, Any]) -> Optional[str]:
    cid = cyc.get("id")
    return str(cid) if cid is not None else None


def cycle_nodes(cyc: Dict[str, Any]) -> List[str]:
    nodes = cyc.get("nodes")
    if isinstance(nodes, list):
        return [str(x) for x in nodes]
    return []


def cycle_pagerank_avg(cyc: Dict[str, Any]) -> float:
    m = cyc.get("metrics")
    if isinstance(m, dict):
        v = m.get("pagerank_avg")
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


@dataclass(frozen=True)
class Candidate:
    repo: str
    branch: str
    lang: str
    cid: str
    size: int
    nodes: Tuple[str, ...]
    bin_key: str
    pagerank_avg: float


def parse_bins(spec: str) -> List[Tuple[int, int, str]]:
    """
    spec like: "2-3,4-6,7-8"
    returns list of (lo, hi, key) preserving input order.
    """
    out: List[Tuple[int, int, str]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError(f"Bad --size-bins item '{part}' (expected 'lo-hi')")
        a, b = part.split("-", 1)
        lo = int(a.strip())
        hi = int(b.strip())
        if lo > hi:
            lo, hi = hi, lo
        out.append((lo, hi, f"{lo}-{hi}"))
    if not out:
        raise ValueError("No bins parsed from --size-bins")
    return out


def bin_for_size(sz: int, bins: List[Tuple[int, int, str]]) -> Optional[str]:
    for lo, hi, key in bins:
        if lo <= sz <= hi:
            return key
    return None


def derive_bin_priority(bins: List[Tuple[int, int, str]]) -> List[str]:
    """
    Deterministic: larger cycles first (by hi desc, then lo desc).
    Example: 2-3,4-6,7-8 => priority 7-8,4-6,2-3
    """
    ordered = sorted(bins, key=lambda t: (t[1], t[0]), reverse=True)
    return [key for _lo, _hi, key in ordered]


# -------------------------
# Selection
# -------------------------

def feasible_under_node_cap(
    cand: Candidate,
    node_use: Dict[str, Counter],
) -> bool:
    ru = node_use[cand.repo]
    for n in cand.nodes:
        if ru.get(n, 0) >= MAX_NODE_USE_PER_REPO:
            return False
    return True


def overlap_count(
    cand: Candidate,
    node_use: Dict[str, Counter],
) -> int:
    ru = node_use[cand.repo]
    return sum(1 for n in cand.nodes if ru.get(n, 0) > 0)


def score_candidate_min(
    cand: Candidate,
    per_repo_selected: Counter,
    node_use: Dict[str, Counter],
) -> Tuple:
    """
    Deterministic lexicographic score where SMALLER is better (so we use min()).

    1) repo fairness: fewer already selected in repo
    2) overlap: fewer reused nodes
    3) size: prefer larger => use negative size
    4) stable tie-break: repo, cid
    """
    selected_in_repo = int(per_repo_selected.get(cand.repo, 0))
    ov = overlap_count(cand, node_use)
    return (
        selected_in_repo,
        ov,
        -cand.size,
        cand.repo,
        cand.cid,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Rebuild per-repo cycle_catalog.json and write cycles_to_analyze.txt.\n"
            "\n"
            "Selection strategy (thesis-friendly):\n"
            "  - size-bin targets (equal split, first bins get remainder)\n"
            "  - bin priority: larger bins first (e.g., 7-8 then 4-6 then 2-3)\n"
            "  - within each bin: global greedy selection across repos with explicit fairness + overlap penalty\n"
            "  - hard cap per repo: --max-per-repo\n"
            f"  - hard node reuse cap per repo: {MAX_NODE_USE_PER_REPO}\n"
            "\n"
            "All tuning constants are fixed in this script for reproducibility."
        )
    )
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--results-root", required=True)
    ap.add_argument("--size-bins", required=True, help='Comma-separated, e.g. "2-3,4-6,7-8"')
    ap.add_argument("--total", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-per-repo", type=int, required=True)
    args = ap.parse_args()

    if args.total <= 0:
        raise SystemExit("--total must be > 0")
    if args.max_per_repo <= 0:
        raise SystemExit("--max-per-repo must be > 0")

    repos_file = Path(args.repos_file).resolve()
    results_root = Path(args.results_root).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bins = parse_bins(args.size_bins)
    bin_priority = derive_bin_priority(bins)
    max_cycle_len_for_generator = max(hi for _lo, hi, _key in bins)

    repos = parse_repos_file(repos_file)
    repos_order = [r for (r, _b, _e, _l) in repos]
    repo_to_branch: Dict[str, str] = {repo: branch for (repo, branch, _e, _l) in repos}
    repo_to_lang: Dict[str, str] = {repo: lang for (repo, _branch, _e, lang) in repos}

    # Build candidate pool (always rebuild cycle_catalog.json)
    import subprocess
    import sys

    pick_cycles_py = Path(__file__).resolve().parent / "pick_cycles.py"

    candidates: List[Candidate] = []
    available_by_bin = Counter()
    available_by_lang = Counter()
    available_by_repo = Counter()
    available_by_bin_repo: Dict[str, Counter] = defaultdict(Counter)
    available_exact_by_repo: Dict[str, Counter] = defaultdict(Counter)

    for repo, branch, _entry, lang in repos:
        atd_dir = results_root / repo / "branches" / branch / "ATD_identification"
        graph_json = atd_dir / "dependency_graph.json"
        scc_report = atd_dir / "scc_report.json"
        catalog_json = atd_dir / "cycle_catalog.json"

        if not graph_json.exists() or not scc_report.exists():
            continue

        cmd = [
            sys.executable,
            str(pick_cycles_py),
            "--dependency-graph", str(graph_json),
            "--scc-report", str(scc_report),
            "--out", str(catalog_json),
            "--repo", repo,
            "--base-branch", branch,
            "--max-cycle-len", str(max_cycle_len_for_generator),
            "--attempts-per-scc", str(ATTEMPTS_PER_SCC),
            "--max-cycles-per-scc", str(MAX_CYCLES_PER_SCC),
            "--seed", str(SEED),
        ]
        print("$ " + " ".join(cmd))
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"[WARN] pick_cycles failed for {repo}@{branch} (rc={rc}); skipping repo")
            continue

        catalog = load_json(catalog_json)
        if not catalog:
            continue

        for cyc in iter_catalog_cycles(catalog):
            sz = cycle_size(cyc)
            cid = cycle_id(cyc)
            nodes = cycle_nodes(cyc)
            if sz is None or cid is None:
                continue

            bkey = bin_for_size(sz, bins)
            if bkey is None:
                continue

            pr_avg = cycle_pagerank_avg(cyc)

            c = Candidate(
                repo=repo,
                branch=branch,
                lang=lang,
                cid=cid,
                size=sz,
                nodes=tuple(nodes),
                bin_key=bkey,
                pagerank_avg=pr_avg,
            )
            candidates.append(c)

            available_by_bin[bkey] += 1
            available_by_lang[lang] += 1
            available_by_repo[repo] += 1
            available_by_bin_repo[bkey][repo] += 1
            available_exact_by_repo[repo][sz] += 1

    if not candidates:
        raise SystemExit("No candidates found. Did you generate dependency_graph.json + scc_report.json?")

    # Bin targets: equal split across bins in the pool (soft targets).
    bins_in_pool = [b for b in bin_priority if available_by_bin.get(b, 0) > 0]
    if not bins_in_pool:
        raise SystemExit("No candidates fell into the requested bins.")

    B = len(bins_in_pool)
    base = args.total // B
    rem = args.total % B
    bin_target: Dict[str, int] = {b: base for b in bins_in_pool}
    # remainder goes to first bins (higher priority bins get slightly more)
    for b in bins_in_pool[:rem]:
        bin_target[b] += 1

    # State
    selected: List[Candidate] = []
    selected_ids: Set[Tuple[str, str]] = set()  # (repo, cid)
    per_repo_selected = Counter()
    per_bin_selected = Counter()
    per_lang_selected = Counter()
    node_use: Dict[str, Counter] = defaultdict(Counter)

    # Index candidates by bin for faster filtering
    cands_by_bin: Dict[str, List[Candidate]] = defaultdict(list)
    for c in candidates:
        cands_by_bin[c.bin_key].append(c)

    # deterministic order inside bins (stable eligibility scanning)
    for b in cands_by_bin:
        cands_by_bin[b].sort(key=lambda c: (c.repo, c.size, c.cid))

    def can_take(c: Candidate) -> bool:
        if (c.repo, c.cid) in selected_ids:
            return False
        if per_repo_selected[c.repo] >= args.max_per_repo:
            return False
        if not feasible_under_node_cap(c, node_use):
            return False
        return True

    def take(c: Candidate) -> None:
        selected.append(c)
        selected_ids.add((c.repo, c.cid))
        per_repo_selected[c.repo] += 1
        per_bin_selected[c.bin_key] += 1
        per_lang_selected[c.lang] += 1
        for n in c.nodes:
            node_use[c.repo][n] += 1

    def pick_best_in_bin(b: str) -> Optional[Candidate]:
        eligible = [c for c in cands_by_bin.get(b, []) if can_take(c)]
        if not eligible:
            return None
        return min(eligible, key=lambda c: score_candidate_min(c, per_repo_selected, node_use))

    # Fill bins in priority order, up to soft targets
    for b in bins_in_pool:
        tgt = int(bin_target.get(b, 0))
        while len(selected) < args.total and per_bin_selected[b] < tgt:
            best = pick_best_in_bin(b)
            if best is None:
                break
            take(best)

    # Spillover: fill remaining slots from bins in priority order, ignoring targets
    for b in bins_in_pool:
        while len(selected) < args.total:
            best = pick_best_in_bin(b)
            if best is None:
                break
            take(best)
        if len(selected) >= args.total:
            break

    # Write output
    lines = [f"{c.repo} {c.branch} {c.cid}" for c in selected]
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    # Summaries
    print(f"Wrote {len(lines)} lines to {out_path}")
    if len(lines) < args.total:
        print(f"[WARN] Requested --total {args.total} but only selected {len(lines)} (insufficient eligible candidates).")

    distinct_repos = sum(1 for r, n in per_repo_selected.items() if n > 0)
    print(f"Distinct repos covered: {distinct_repos}")
    print(f"Generator max-cycle-len (derived from bins): {max_cycle_len_for_generator}")
    print(f"Max per repo: {args.max_per_repo}")
    print(f"Node reuse cap per repo: {MAX_NODE_USE_PER_REPO}")
    print(f"Bin priority order: {', '.join(bins_in_pool)}")

    print("Size-bin targets (soft):")
    for b in bins_in_pool:
        tgt = bin_target.get(b, 0)
        sel = per_bin_selected.get(b, 0)
        short = max(0, int(tgt) - int(sel))
        extra = max(0, int(sel) - int(tgt))
        note = ""
        if short > 0:
            note = f" shortfall={short}"
        elif extra > 0:
            note = f" excess={extra}"
        print(
            f"  bin={b}: target={tgt} available={available_by_bin.get(b,0)} selected={sel}{note}"
        )

    print("Language availability:")
    for lang, a in sorted(available_by_lang.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {lang}: available={a} selected={per_lang_selected.get(lang,0)}")

    print("Selected per repo:")
    for repo in repos_order:
        n = per_repo_selected.get(repo, 0)
        if n > 0:
            print(f"  {repo}: {n}")

    # Bin availability / selection (top repos)
    def fmt_top(counter: Counter, k: int = 8) -> str:
        items = counter.most_common(k)
        return ", ".join(f"{r}={n}" for r, n in items)

    print("Availability by bin (top repos):")
    for b in bins_in_pool:
        print(f"  bin={b} total={available_by_bin.get(b,0)} top: {fmt_top(available_by_bin_repo[b])}")

    selected_by_bin_repo: Dict[str, Counter] = defaultdict(Counter)
    for c in selected:
        selected_by_bin_repo[c.bin_key][c.repo] += 1

    print("Selected by bin (top repos):")
    for b in bins_in_pool:
        print(f"  bin={b} total={per_bin_selected.get(b,0)} top: {fmt_top(selected_by_bin_repo[b])}")

    # Per-repo exact sizes: available vs selected
    selected_exact_by_repo: Dict[str, Counter] = defaultdict(Counter)
    for c in selected:
        selected_exact_by_repo[c.repo][c.size] += 1

    size_values: List[int] = []
    for lo, hi, _key in bins:
        size_values.extend(list(range(lo, hi + 1)))
    size_values = sorted(set(size_values))

    print("Per-repo exact cycle sizes: available vs selected")
    for repo in repos_order:
        avail = available_exact_by_repo.get(repo, Counter())
        sel = selected_exact_by_repo.get(repo, Counter())
        if not avail and not sel:
            continue

        print(f"Repo: {repo} (lang={repo_to_lang.get(repo,'unknown')}, branch={repo_to_branch.get(repo,'')})")
        for sz in size_values:
            a = int(avail.get(sz, 0))
            s = int(sel.get(sz, 0))
            print(f"  size={sz}: available={a} selected={s}")

    # Overlap summary
    print("Overlap summary (per repo):")
    for repo in repos_order:
        ru = node_use.get(repo)
        if not ru:
            continue
        max_use = max(ru.values()) if ru else 0
        nodes_ge2 = sum(1 for _n, v in ru.items() if v >= 2)
        distinct_nodes = len(ru)
        print(f"  {repo}: max_node_use={max_use} nodes_used>=2={nodes_ge2} distinct_nodes={distinct_nodes}")

    print("Done.")


if __name__ == "__main__":
    main()