from __future__ import annotations

from typing import Dict, List


BASE_TEMPLATE = """Please refactor to break this dependency cycle:

Cycle size: {size}
{chain}

Remove preferably just one static edge, ensuring no new cycles are introduced and behavior remains unchanged.

Important:
- My ATD metric treats ANY module/type reference as a dependency (dynamic/lazy all count).
- So making imports dynamic or lazy is NOT sufficient.
- We care about architecture (static coupling), not runtime import order.
- Type-only references under TYPE_CHECKING do NOT count as dependencies (Python).

Done when:
- The cycle is broken
- All public APIs remain identical
- Tests pass confirming no behavioral changes
- No new cycles are created in the dependency graph

How to check that an edge A->B in the cycle has been successfully broken:
- There is not a single import/reference from B in file A (except if under TYPE_CHECKING in Python).
- If you introduce a new file, do not just make the cycle longer (e.g., A->C->B->A).
- It is not enough to remove some imports/references: for the chosen broken edge, ALL relevant references must be removed.
"""


def _pretty_node(node_id: str) -> str:
    return (node_id or "").strip().replace("\\", "/") or "<?>"


def cycle_chain_str(nodes: List[str]) -> str:
    if not nodes:
        return "N/A"
    pretty = [_pretty_node(n) for n in nodes]
    return " -> ".join(pretty + [pretty[0]])


def build_minimal_prompt(cycle_nodes: List[str]) -> str:
    nodes = [str(n) for n in (cycle_nodes or [])]
    size = len(nodes)
    chain = cycle_chain_str(nodes)
    return BASE_TEMPLATE.format(size=size, chain=chain).rstrip() + "\n"
