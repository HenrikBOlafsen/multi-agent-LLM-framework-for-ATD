#!/usr/bin/env python3
"""
explain_cycle_minimal.py
Generates a minimal refactoring prompt (no explanations), given a cycle id.

Usage:
  python explain_cycle_minimal.py \
    --repo-root <path> \
    --src-root <rel/package/root> \
    --cycle-json <path/to/module_cycles.json> \
    --cycle-id <scc_X_cycle_Y> \
    --out-prompt <path/to/output.txt>
"""

import argparse, json
from pathlib import Path

TEMPLATE = """Please refactor to break this dependency cycle:

Cycle size: {size}
{chain}

Remove exactly one static edge, ensuring no new cycles are introduced and behavior remains unchanged.

Please refactor to break this cycle, without increasing architectural technical debt elsewhere (e.g., no new cycles). My ATD metric treats ANY module reference as a dependency (dynamic/lazy all count). So making imports dynamic or lazy is NOT sufficient. I care about architecture (static coupling), not just runtime import order.

Done when
- The cycle is broken
- All public APIs remain identical
- Tests pass confirming no behavioral changes
- No new cycles are created in the dependency graph

This is how you check that the edge A->B in the cycle has been successfully broken:
- There is not a single import X from B or import B in the script A. Not as top-level import and not even as a nested import inside a function or class or whatever (except if under TYPE_CHECKING).
- If you introduce a new file, make sure the new file does not just make the cycle longer. E.g. if new file is C, don't make A->B->A into A->C->B->A.
- Make sure the dependency is not just partially broken. It is not enough to remove just some of the imports. They ALL need to be removed (For the given edge. Except if under TYPE_CHECKING).
"""

def load_cycle(cycles_path: Path, cycle_id: str):
    data = json.loads(cycles_path.read_text(encoding="utf-8"))
    sccs = data.get("sccs") or []
    for s in sccs:
        reps = s.get("representative_cycles") or s.get("cycles") or []
        for c in reps:
            cid = c.get("id") or c.get("cycle_id")
            if cid == cycle_id:
                return c
    raise KeyError(f"Cycle id '{cycle_id}' not found in {cycles_path}")

def pretty_module_name(node: str) -> str:
    name = (node or "").strip()
    if name.endswith(".py"):
        name = name[:-3]
    name = name.replace("\\", "/")
    if name.startswith("./"):
        name = name[2:]
    name = name.replace("/", ".")
    if name.endswith(".__init__"):
        name = name[:-9]
    return name or "<?>"

def cycle_chain_str(nodes):
    if not nodes:
        return "N/A"
    pretty = [pretty_module_name(n) for n in nodes]
    return " -> ".join(pretty + [pretty[0]])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--src-root", required=True)
    ap.add_argument("--cycle-json", required=True)
    ap.add_argument("--cycle-id", required=True)
    ap.add_argument("--out-prompt", required=True)
    args = ap.parse_args()

    cyc = load_cycle(Path(args.cycle_json), args.cycle_id)
    size = cyc.get("length") or len(cyc.get("nodes") or [])
    chain = cycle_chain_str(cyc.get("nodes") or [])

    prompt = TEMPLATE.format(size=size, chain=chain)

    outp = Path(args.out_prompt)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(prompt, encoding="utf-8")
    print(prompt)

if __name__ == "__main__":
    main()
