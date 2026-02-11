#!/usr/bin/env python3
# Run using:
#   python3 test_runs/assert_toydotnet_edges.py

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]  # repo root (test_runs/..)
TOY_REPO = ROOT / "projects_to_analyze" / "ToyDotnetRepo"
ENTRY = "src/ToyDotnetRepo"  # entry subdir passed to analyzer (must exist under repo)
OUT = ROOT / "test_runs" / "_tmp_toydotnet_out"

ANALYZE_SH = ROOT / "ATD_identification" / "analyze_cycles_dotnet.sh"


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
        raise SystemExit(f"analyze_cycles_dotnet.sh failed (rc={rc})")

    graph_path = OUT / "dependency_graph.json"
    if not graph_path.exists():
        raise SystemExit(f"Missing dependency_graph.json: {graph_path}")
    if graph_path.stat().st_size == 0:
        raise SystemExit(f"Empty dependency_graph.json: {graph_path}")


def main() -> None:
    run_analyzer()

    graph_path = OUT / "dependency_graph.json"
    nodes, edges = load_graph(graph_path)

    # Repo-relative node ids (relative to ToyDotnetRepo root)
    AUDIT = "src/ToyDotnetRepo/ToyDotnetRepo/Common/AuditedAttribute.cs"

    A = "src/ToyDotnetRepo/ToyDotnetRepo/Core/A.cs"
    B = "src/ToyDotnetRepo/ToyDotnetRepo/Core/B.cs"
    C = "src/ToyDotnetRepo/ToyDotnetRepo/Core/C.cs"

    ISVC = "src/ToyDotnetRepo/ToyDotnetRepo/Core/IService.cs"
    SVC_IMPL = "src/ToyDotnetRepo/ToyDotnetRepo/Core/ServiceImpl.cs"
    SVC_EXT = "src/ToyDotnetRepo/ToyDotnetRepo/Core/ServiceExtensions.cs"
    USES_SVC = "src/ToyDotnetRepo/ToyDotnetRepo/Core/UsesServiceInterfaceOnly.cs"
    USES_EXT = "src/ToyDotnetRepo/ToyDotnetRepo/Core/UsesExtensionMethod.cs"

    WIDGET = "src/ToyDotnetRepo/ToyDotnetRepo/Partials/Widget.Part1.cs"
    USES_WIDGET = "src/ToyDotnetRepo/ToyDotnetRepo/Core/UsesWidget.cs"
    ALIAS_WIDGET = "src/ToyDotnetRepo/ToyDotnetRepo/Core/AliasUsesWidget.cs"
    TYPEOF_WIDGET = "src/ToyDotnetRepo/ToyDotnetRepo/Core/TypeOfUsesWidget.cs"
    NAMEOF_WIDGET = "src/ToyDotnetRepo/ToyDotnetRepo/Core/NameOfUsesWidget.cs"
    UNUSED_USING = "src/ToyDotnetRepo/ToyDotnetRepo/Core/UnusedUsing.cs"

    # Ensure nodes exist (helps catch “file skipped” bugs)
    must_have_nodes(
        nodes,
        [
            AUDIT, A, B, C,
            ISVC, SVC_IMPL, SVC_EXT, USES_SVC, USES_EXT,
            WIDGET, USES_WIDGET, ALIAS_WIDGET, TYPEOF_WIDGET, NAMEOF_WIDGET, UNUSED_USING,
        ],
    )

    # --- Must exist (positive edges) ---
    must_have(edges, A, B)
    must_have(edges, A, AUDIT)
    must_have(edges, B, C)
    must_have(edges, C, A)  # cycle

    must_have(edges, USES_SVC, ISVC)
    must_have(edges, SVC_IMPL, ISVC)
    must_have(edges, USES_EXT, ISVC)  # field/ctor uses IService even if call is extension

    must_have(edges, USES_WIDGET, WIDGET)
    must_have(edges, ALIAS_WIDGET, WIDGET)
    must_have(edges, TYPEOF_WIDGET, WIDGET)

    # nameof(...) is treated as a string-level reference, not structural type coupling.
    must_not_have(edges, NAMEOF_WIDGET, WIDGET)

    # --- Must NOT exist (negative edges) ---
    must_not_have(edges, UNUSED_USING, WIDGET)      # unused using shouldn't create a type dependency
    must_not_have(edges, USES_EXT, SVC_EXT)         # extension method call shouldn't add dependency to defining class

    print("✅ ToyDotnetRepo edge assertions passed.")


if __name__ == "__main__":
    main()
