from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EdgePromptVariant:
    variant_id: str
    preamble: str
    output_headings: str


BASE_RULES = """You are an Edge Agent analyzing one dependency edge A -> B inside a dependency cycle.

Rules:
- Stay grounded in the code and file paths/names.
- Stay factual. If unsure, say so.
- No tables, no JSON.
- Keep it concise, but do not omit important dependency details.
- If you see truncation notes, assume some context may be missing.
- In your response, use the real file names instead of calling them A and B.
"""


def make_preamble(extra_rules: str = "") -> str:
    return BASE_RULES + extra_rules


EDGE_VARIANTS = {
    "E0": EdgePromptVariant(
        variant_id="E0",
        preamble=make_preamble("""
Additional rules:
- Do not propose refactorings. Your job is to explain what the dependency is and how it is used.
"""),
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Edge
Where in A
What from B
How A uses it
Notes / uncertainty
""",
    ),

    "E1": EdgePromptVariant(
        variant_id="E1",
        preamble=make_preamble("""
Additional rules:
- You may cautiously infer intent from naming and folder structure, but label it as interpretation.
"""),
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Edge
Where in A
What from B
How A uses it
Likely intent (cautious)
Notes / uncertainty
""",
    ),

    "E2": EdgePromptVariant(
        variant_id="E2",
        preamble=make_preamble("""
Additional rules:
- You may propose 1-2 plausible decoupling options, clearly marked as suggestions.
"""),
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Edge
Where in A
What from B
How A uses it
Decoupling ideas (1-2, cautious)
Notes / uncertainty
""",
    ),
}


def require_edge_variant(variant_id: str) -> EdgePromptVariant:
    v = EDGE_VARIANTS.get((variant_id or "").strip())
    if v is None:
        raise ValueError(f"edge_variant must be one of {sorted(EDGE_VARIANTS.keys())} (got {variant_id!r})")
    return v