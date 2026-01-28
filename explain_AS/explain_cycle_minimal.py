#!/usr/bin/env python3
from __future__ import annotations

from typing import Dict, List


TEMPLATE = """Please refactor to break this dependency cycle:

Cycle size: {size}
{chain}

Remove preferably just one static edge, ensuring no new cycles are introduced and behavior remains unchanged.

Please refactor to break this cycle, without increasing architectural technical debt elsewhere (e.g., no new cycles). My ATD metric treats ANY module reference as a dependency (dynamic/lazy all count). So making imports dynamic or lazy is NOT sufficient. I care about architecture (static coupling), not just runtime import order.

Make sure code quality actually improves from your refactoring. Do not apply hacky bad solutions just to break the cycle. Do it properly

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


def pretty_node(node_id: str) -> str:
    # node_id is repo-relative file path. For readability, show the path.
    s = (node_id or "").strip().replace("\\", "/")
    return s or "<?>"


def cycle_chain_str(nodes: List[str]) -> str:
    if not nodes:
        return "N/A"
    pretty = [pretty_node(n) for n in nodes]
    return " -> ".join(pretty + [pretty[0]])


def build_minimal_prompt(cycle: Dict) -> str:
    nodes = cycle.get("nodes") or []
    size = int(cycle.get("length") or len(nodes))
    chain = cycle_chain_str([str(n) for n in nodes])
    return TEMPLATE.format(size=size, chain=chain)
