#!/usr/bin/env python3
# Run using:
#   python3 test_runs/assert_toypython_edges.py

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]  # repo root if stored in test_runs/
TOY_REPO = ROOT / "projects_to_analyze" / "ToyPythonRepo"
ENTRY = "src/toypythonrepo"
OUT = ROOT / "test_runs" / "_tmp_toypython_out"

ANALYZE_SH = ROOT / "ATD_identification" / "analyze_cycles.sh"


def load_graph(dep_graph_path: Path) -> tuple[set[str], set[tuple[str, str]]]:
    try:
        data = json.loads(dep_graph_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"Failed to parse dependency graph JSON: {dep_graph_path} ({e})")

    nodes: set[str] = set()
    for n in data.get("nodes", []):
        if not isinstance(n, dict):
            raise SystemExit(f"Bad node entry (expected dict): {n}")
        nid = n.get("id")
        if isinstance(nid, str):
            nodes.add(nid)
        else:
            raise SystemExit(f"Bad node id (expected str): {n}")

    edges: set[tuple[str, str]] = set()
    for e in data.get("edges", []):
        if not isinstance(e, dict):
            raise SystemExit(f"Bad edge entry (expected dict): {e}")
        s = e.get("source")
        t = e.get("target")
        if isinstance(s, str) and isinstance(t, str):
            edges.add((s, t))
        else:
            raise SystemExit(f"Bad edge object (missing source/target strings): {e}")

    return nodes, edges


def must_have(edges: set[tuple[str, str]], s: str, t: str) -> None:
    if (s, t) not in edges:
        raise SystemExit(f"Missing expected edge: {s} -> {t}")


def must_not_have(edges: set[tuple[str, str]], s: str, t: str) -> None:
    if (s, t) in edges:
        raise SystemExit(f"Unexpected edge present: {s} -> {t}")


def must_have_nodes(nodes: set[str], expected: list[str]) -> None:
    missing = [n for n in expected if n not in nodes]
    if missing:
        raise SystemExit("Missing expected node(s):\n  " + "\n  ".join(missing))


def run_analyzer() -> None:
    if not TOY_REPO.exists():
        raise SystemExit(f"Toy repo missing: {TOY_REPO}")
    if not (TOY_REPO / ".git").exists():
        raise SystemExit(f"Toy repo is not a git repo (missing .git): {TOY_REPO}")
    if not (TOY_REPO / ENTRY).exists():
        raise SystemExit(f"Entry directory missing: {TOY_REPO / ENTRY}")
    if not ANALYZE_SH.exists():
        raise SystemExit(f"Analyzer script missing: {ANALYZE_SH}")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    cmd = ["bash", str(ANALYZE_SH), str(TOY_REPO), ENTRY, str(OUT)]
    print("$ " + " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        raise SystemExit(f"analyze_cycles.sh failed (rc={rc})")

    graph_path = OUT / "dependency_graph.json"
    if not graph_path.exists():
        raise SystemExit(f"Missing dependency_graph.json: {graph_path}")
    if graph_path.stat().st_size == 0:
        raise SystemExit(f"Empty dependency_graph.json: {graph_path}")


def main() -> None:
    run_analyzer()

    graph_path = OUT / "dependency_graph.json"
    nodes, edges = load_graph(graph_path)

    # Node ids are repo-relative file paths
    A = "src/toypythonrepo/a.py"
    B = "src/toypythonrepo/b.py"
    C = "src/toypythonrepo/c.py"
    D = "src/toypythonrepo/d.py"
    TYPECHECK = "src/toypythonrepo/typecheck_only.py"
    ALIAS = "src/toypythonrepo/alias_import.py"
    REL = "src/toypythonrepo/relative_imports.py"
    HELPER = "src/toypythonrepo/subpkg/helper.py"
    USES_VENDOR = "src/toypythonrepo/uses_vendor.py"
    VENDOR = "src/toypythonrepo/vendors/vendormod.py"

    must_have_nodes(nodes, [A, B, C, D, TYPECHECK, ALIAS, REL, HELPER, USES_VENDOR])
    # Note: vendor module should be excluded as a node if your extractor skips vendors/.
    # If you *do* include vendor files as nodes but exclude edges to them, add VENDOR above.

    # Must exist
    must_have(edges, A, B)
    must_have(edges, B, C)
    must_have(edges, C, A)
    must_have(edges, ALIAS, B)
    must_have(edges, REL, B)
    must_have(edges, REL, HELPER)

    # Must NOT exist
    must_not_have(edges, TYPECHECK, D)
    must_not_have(edges, USES_VENDOR, VENDOR)

    print("✅ ToyPythonRepo edge assertions passed.")


if __name__ == "__main__":
    main()
