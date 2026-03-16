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
- If you see truncation notes, assume some context may be missing.
- In your response, use the real file names instead of calling them A and B.
- Base summaries on the specific facts in the provided reports and context. Avoid generic statements and avoid just listing the cycle dependencies.
"""


def make_preamble(extra_rules: str = "") -> str:
    return BASE_RULES + extra_rules


EDGE_VARIANTS = {
    "E0": EdgePromptVariant(
        variant_id="E0",
        preamble=make_preamble("""
Additional rules:
- Do not propose refactorings. Your job is to explain what the dependency is, how it is used, and why it exists in this design.
- Go beyond naming symbols: explain the role that the dependency plays in A when that is visible from the code.
- Do not quote code (no snippets/excerpts). Refer to identifiers and describe usage in words.
"""),
        output_headings="""Output format (must follow exactly these headings, in this order):
Dependency summary
Where in A
What from B
How A uses it
Why A depends on it
Notes / uncertainty (if any)
""",
    ),

    "E1": EdgePromptVariant(
        variant_id="E1",
        preamble=make_preamble("""
Additional rules:
- Your job is to shorten the provided code into a dependency-focused summary of this edge.
- Focus on the parts of the code that explain the dependency, but keep enough surrounding context so the role of the file remains understandable.
- Omit clearly irrelevant details.
- Do not give refactoring advice.
- You may include small code excerpts if they clarify the dependency, but avoid dumping code.
"""),
        output_headings="""Output format (must follow exactly these headings, in this order):
Dependency summary
Dependency-focused code summary
Notes / uncertainty (if any)
""",
    ),

    "E2": EdgePromptVariant(
        variant_id="E2",
        preamble=make_preamble("""
Additional rules:
- You may propose 1-2 plausible decoupling options, clearly marked as suggestions.
"""),
        output_headings="""Output format (must follow exactly these headings, in this order):
Dependency summary
Where in A
What from B
How A uses it
Decoupling ideas (1-2, cautious)
Notes / uncertainty (if any)
""",
    ),
}


def require_edge_variant(variant_id: str) -> EdgePromptVariant:
    v = EDGE_VARIANTS.get((variant_id or "").strip())
    if v is None:
        raise ValueError(f"edge_variant must be one of {sorted(EDGE_VARIANTS.keys())} (got {variant_id!r})")
    return v