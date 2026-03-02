from __future__ import annotations

from typing import List

from context import require_language
from language import edge_semantics_text


BASE_TEMPLATE = """Please refactor to break this dependency cycle:

{semantics}

Cycle size: {size}
{chain}

Break the cycle by removing at minimum one edge, ensuring no new cycles are introduced and behavior remains unchanged.

Important:
- My ATD metric treats ANY module/type reference as a dependency, so making imports dynamic or lazy is NOT sufficient (unless it no longer counts as a dependency per the rules above).
- We care about architecture (static coupling), not runtime import order.
- We want to actually improve code architecture by reducing cyclic coupling, so do not use hacky solutions to break the cycles.

Done when:
- The cycle is broken
- All public APIs remain identical
- Tests pass, confirming no behavioral changes
- No new cycles are created in the dependency graph
- Code quality/maintainability/architecture has been improved

How to check that an edge A->B in the cycle has been successfully broken:
- There must not be even a single dependency from B in file A, as defined by the language-specific rules above.
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


def build_minimal_prompt(cycle_nodes: List[str], language: str) -> str:
    language = require_language(language)

    nodes = [str(n) for n in (cycle_nodes or [])]
    size = len(nodes)
    chain = cycle_chain_str(nodes)
    semantics = edge_semantics_text(language)

    return (
        BASE_TEMPLATE.format(
            semantics=semantics,
            size=size,
            chain=chain,
        ).rstrip()
        + "\n"
    )