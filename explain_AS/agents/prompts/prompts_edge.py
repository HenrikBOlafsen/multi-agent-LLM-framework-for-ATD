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
        output_headings="""Output format (MUST follow exactly these headings, in this order):
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
- Compression-first: your primary job is to compress the provided code into a small, high-signal description of this specific dependency edge.
- Keep only what is most relevant to explaining why A depends on B under the given edge semantics.
- Include just enough detail that a downstream agent could reconstruct the dependency story (key identifiers and the minimal call/usage shape).
- Prefer referring to identifiers (classes, functions, methods, fields, constants) instead of quoting large code blocks.
- You may include small code excerpts if they clarify the dependency, but avoid dumping code.
- If context appears truncated, mention the uncertainty instead of guessing.
- You may cautiously infer intent from naming and folder structure, but clearly label it as interpretation.
"""),
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Dependency summary
Compressed evidence of the dependency
Notes / uncertainty (if any)
""",
    ),

    "E2": EdgePromptVariant(
        variant_id="E2",
        preamble=make_preamble("""
Additional rules:
- You may propose 1-2 plausible decoupling options, clearly marked as suggestions.
"""),
        output_headings="""Output format (MUST follow exactly these headings, in this order):
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