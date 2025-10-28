#!/usr/bin/env python3
"""
summarize_all_repos.py  —  Paper-oriented repo overview aligned to pydeps

Inputs:
  - repos.txt lines: "<repo> <branch> <src_rel>"
  - results/<repo>/<branch>/ATD_identification/pydeps.json        -> modules, deps, module file paths (preferred)
  - results/<repo>/<branch>/ATD_identification/ATD_metrics.json   -> SCC totals (nodes/edges/loc in cycles, etc.)
  - results/<repo>/<branch>/ATD_identification/module_cycles.json -> representative cycles (median length)
  - projects_root/<repo>/<src_rel>                                -> fallback path resolution if pydeps lacks paths

Output CSV columns:
  id,label,loc_k,modules,deps,sccs,
  nodes_in_cycles,edges_in_cycles,loc_in_cycles_k,
  pct_modules_in_cycles,pct_deps_in_cycles,
  max_scc_size,avg_scc_size,rep_cycle_len_med

Run:
  python summarize_all_repos.py --repos-file repos.txt \
    --projects-root projects_to_analyze --results-root results \
    --out repos_overview_enriched.csv
"""

from __future__ import annotations
import argparse, os, json, re, statistics
from typing import Dict, List, Tuple, Any, Iterable, Set

# ---------- stable mapping to paper IDs/labels ----------
REPO_ID_LABEL = {
    "kombu":    ("P1", "Message Queue Library"),
    "click":    ("P2", "CLI Framework"),
    "werkzeug": ("P3", "Web Server Utility"),
    "rich":     ("P4", "Terminal UI Library"),
    "jinja":    ("P5", "Template Engine"),
    "celery":   ("P6", "Task Queue Framework"),
    "lark":     ("P7", "Parsing Toolkit"),
}

# ---------- repos.txt ----------
def read_repos_file(path: str) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 3:
                print(f"[WARN] Skipping malformed line: {s}")
                continue
            repo, branch, src_rel = parts[0], parts[1], " ".join(parts[2:])
            rows.append((repo, branch, src_rel))
    return rows

# ---------- pydeps helpers ----------
def _normalize_pydeps(pydeps_json: str) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """
    Return (imports, paths) in normalized form.
    Supports:
      A) {"imports": {"a.b": ["c.d", ...], ...}}
      B) {"a.b": {"imports": [...], "path": "..."} , ...}
    """
    raw = json.load(open(pydeps_json, "r", encoding="utf-8"))
    # style A
    if isinstance(raw, dict) and "imports" in raw and isinstance(raw["imports"], dict):
        imports = raw["imports"]
        paths: Dict[str, str] = {}
        # sometimes top-level may also contain per-module objects; ignore for A
        return imports, paths
    # style B
    imports = {m: (obj.get("imports") or []) for m, obj in raw.items() if isinstance(obj, dict)}
    paths   = {m: obj.get("path")            for m, obj in raw.items() if isinstance(obj, dict)}
    return imports, paths

def _module_to_path_guess(mod: str, src_dir: str, top_pkg: str) -> str | None:
    """
    Fallback: map 'pkg.sub.mod' -> '<src_dir>/sub/mod.py' (and try __init__.py for packages).
    We only guess inside the top package.
    """
    if not (mod == top_pkg or mod.startswith(top_pkg + ".")):
        return None
    rel = mod[len(top_pkg):].lstrip(".")  # remove leading 'pkg.'
    candidate = os.path.join(src_dir, rel.replace(".", os.sep) + ".py")
    if os.path.isfile(candidate):
        return os.path.realpath(candidate)
    # package __init__.py
    initp = os.path.join(src_dir, rel.replace(".", os.sep), "__init__.py")
    if os.path.isfile(initp):
        return os.path.realpath(initp)
    return None

def collect_internal_module_files(pydeps_json: str, src_dir: str, top_pkg: str) -> Tuple[Set[str], int, int]:
    """
    Build the *set of absolute file paths* for internal modules from pydeps,
    plus (modules_count, deps_count).

    - Prefer module "path" fields from pydeps when available.
    - Otherwise, guess file paths from module names under top package.
    - Only count edges among internal modules for 'deps'.
    """
    imports, paths = _normalize_pydeps(pydeps_json)

    internal_mods = set(imports.keys())
    # deps: edges where target is also internal and distinct from src
    deps_count = 0
    for src, tgts in imports.items():
        if src not in internal_mods:
            continue
        for t in (tgts or []):
            if t in internal_mods and t != src:
                deps_count += 1

    files: Set[str] = set()
    for m in internal_mods:
        p = paths.get(m)
        if p and os.path.isfile(p):
            files.add(os.path.realpath(p))
        else:
            g = _module_to_path_guess(m, src_dir, top_pkg)
            if g:
                files.add(g)

    return files, len(internal_mods), deps_count

# ---------- LoC helpers ----------
def count_loc_in_files(files: Iterable[str]) -> int:
    total = 0
    for p in files:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                total += sum(1 for line in fh if line.strip())
        except Exception:
            pass
    return total

# ---------- ATD + cycles ----------
def load_atd_metrics(atd_json: str) -> Dict[str, Any]:
    try:
        with open(atd_json, "r", encoding="utf-8") as f:
            j = json.load(f)
        return {
            "scc_count": j.get("scc_count"),
            "nodes_in_cycles": j.get("total_nodes_in_cyclic_sccs"),
            "edges_in_cycles": j.get("total_edges_in_cyclic_sccs"),
            "loc_in_cycles":   j.get("total_loc_in_cyclic_sccs"),
            "max_scc_size":    j.get("max_scc_size"),
            "avg_scc_size":    j.get("avg_scc_size"),
        }
    except Exception as e:
        print(f"  [WARN] Failed to read ATD_metrics.json: {e}")
        return {}

def load_rep_cycle_len_median(mod_cycles_json: str) -> float | None:
    try:
        with open(mod_cycles_json, "r", encoding="utf-8") as f:
            j = json.load(f)
        reps = j.get("representative_cycles") or []
        lengths = [rc.get("length") for rc in reps if isinstance(rc.get("length"), (int, float))]
        return float(statistics.median(lengths)) if lengths else None
    except Exception:
        return None

# ---------- formatting ----------
def fmt_k_lines(n: int | None) -> str:
    if not isinstance(n, (int, float)):
        return ""
    # 1 decimal in thousands
    return f"{round(float(n)/100.0)/10.0:.1f}"

def pct(numer: int | None, denom: int | None) -> str:
    try:
        if numer is None or denom in (None, 0):
            return ""
        return f"{(100.0*float(numer)/float(denom)):.1f}"
    except Exception:
        return ""

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos-file", required=True)
    ap.add_argument("--projects-root", default="projects_to_analyze")
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--out", default="", help="CSV path; if omitted, print at end")
    args = ap.parse_args()

    items = read_repos_file(args.repos_file)
    rows_out: List[List[str]] = []

    header = [
        "id","label","loc_k","modules","deps","sccs",
        "nodes_in_cycles","edges_in_cycles","loc_in_cycles_k",
        "pct_modules_in_cycles","pct_deps_in_cycles",
        "max_scc_size","avg_scc_size","rep_cycle_len_med"
    ]

    print(f"[INFO] Repositories to summarize: {len(items)}")
    for i, (repo, branch, src_rel) in enumerate(items, start=1):
        rid, label = REPO_ID_LABEL.get(repo, (repo, repo.title()))
        print(f"[{i}/{len(items)}] {repo}@{branch}: start")

        # Paths
        src_dir = os.path.realpath(os.path.join(args.projects_root, repo, src_rel))
        if not os.path.isdir(src_dir):
            print(f"  [WARN] src dir not found: {src_dir}")
        top_pkg = os.path.basename(src_dir.rstrip("/"))

        res_dir = os.path.join(args.results_root, repo, branch, "ATD_identification")
        pydeps_json = os.path.join(res_dir, "pydeps.json")
        atd_metrics_json = os.path.join(res_dir, "ATD_metrics.json")
        mod_cycles_json = os.path.join(res_dir, "module_cycles.json")

        modules = deps = None
        loc_lines = None

        # pydeps -> modules/deps + internal module files (for LoC)
        if os.path.isfile(pydeps_json):
            try:
                files, modules, deps = collect_internal_module_files(pydeps_json, src_dir, top_pkg)
                loc_lines = count_loc_in_files(files)
                print(f"  Graph: modules={modules}, deps={deps}, files_for_loc={len(files)}, loc≈{fmt_k_lines(loc_lines)}K")
            except Exception as e:
                print(f"  [WARN] Failed to process pydeps.json: {e}")
        else:
            print(f"  [WARN] pydeps.json not found: {pydeps_json}")

        # ATD_metrics -> SCC stats
        sccs = nodes_in_cycles = edges_in_cycles = loc_in_cycles = max_scc_size = avg_scc_size = None
        if os.path.isfile(atd_metrics_json):
            m = load_atd_metrics(atd_metrics_json)
            sccs = m.get("scc_count")
            nodes_in_cycles = m.get("nodes_in_cycles")
            edges_in_cycles = m.get("edges_in_cycles")
            loc_in_cycles = m.get("loc_in_cycles")
            max_scc_size = m.get("max_scc_size")
            avg_scc_size = m.get("avg_scc_size")
            print(f"  SCCs={sccs}; nodes_in_cycles={nodes_in_cycles}; edges_in_cycles={edges_in_cycles}")
        else:
            print(f"  [WARN] ATD_metrics.json not found: {atd_metrics_json}")

        # module_cycles -> representative cycle median length
        rep_cycle_len_med = None
        if os.path.isfile(mod_cycles_json):
            rep_cycle_len_med = load_rep_cycle_len_median(mod_cycles_json)
            if rep_cycle_len_med is not None:
                print(f"  Representative cycles: median_len={rep_cycle_len_med:.1f}")
            else:
                print("  Representative cycles: none")
        else:
            print(f"  [WARN] module_cycles.json not found: {mod_cycles_json}")

        # derived % (requires modules/deps)
        pct_modules = pct(nodes_in_cycles, modules if isinstance(modules, int) else None)
        pct_deps = pct(edges_in_cycles, deps if isinstance(deps, int) else None)

        row = [
            rid,
            label,
            fmt_k_lines(loc_lines) if loc_lines is not None else "",
            str(modules) if isinstance(modules, int) else "",
            str(deps) if isinstance(deps, int) else "",
            str(sccs) if sccs is not None else "",
            str(nodes_in_cycles) if nodes_in_cycles is not None else "",
            str(edges_in_cycles) if edges_in_cycles is not None else "",
            fmt_k_lines(loc_in_cycles) if isinstance(loc_in_cycles, (int, float)) else "",
            pct_modules,
            pct_deps,
            str(max_scc_size) if max_scc_size is not None else "",
            (f"{float(avg_scc_size):.1f}" if isinstance(avg_scc_size, (int, float)) else ""),
            (f"{float(rep_cycle_len_med):.1f}" if isinstance(rep_cycle_len_med, (int, float)) else ""),
        ]
        rows_out.append(row)
        print(f"[{i}/{len(items)}] {repo}@{branch}: done")

    # Emit CSV at the end
    lines = [",".join(header)]
    for r in rows_out:
        lines.append(",".join(r))
    csv_text = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(csv_text + "\n")
        print(f"[INFO] Wrote CSV to {args.out}")
    else:
        print("\n" + csv_text)

if __name__ == "__main__":
    main()
