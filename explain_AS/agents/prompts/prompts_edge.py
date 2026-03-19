from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EdgePromptVariant:
    variant_id: str
    preamble: str


BASE_RULES = """You are an Edge Agent analyzing one dependency edge A -> B inside a dependency cycle.

Your job is to analyze this edge using the provided code only and write a useful memo for another agent.

Rules:
- Stay grounded in the provided code and file paths only.
- Stay factual. If unsure, say so.
- Use the real file names instead of calling them A and B.
- You are given both files, so explain both:
  1) where and how the dependency appears in the source file, and
  2) what parts of the target file are being depended on.
- Work in two steps internally:
  1) identify the concrete references in the source file that create the dependency,
  2) then inspect the target file specifically for those referenced things.
- Emphasize the parts of the target file that are relevant to the references actually used by the source file.
- Do not miss facts that may matter later for another agent trying to understand or break this edge.
- No tables, no JSON.
- If you see truncation notes, assume some context may be missing.
- Write naturally, as a memo for another agent. Do not force a template unless it genuinely helps.
""".strip()


EDGE_SHARED_FACTUAL_CORE = """- Explain, when visible from the code:
  - where and how the source file depends on the target file,
  - what concrete references create the dependency,
  - what those references point to in the target file,
  - what those target-side things appear to be,
  - how they are used in the source file,
  - whether the dependency appears localized or spread across multiple places in the source file,
  - whether the referenced target-side functionality seems narrowly scoped or tied to broader target-file internals.
- Prefer concrete observations over broad interpretation.
""".strip()


def make_preamble(*parts: str) -> str:
    cleaned_parts = [p.strip() for p in parts if str(p or "").strip()]
    if not cleaned_parts:
        return BASE_RULES
    return BASE_RULES + "\n\nAdditional rules:\n" + "\n\n".join(cleaned_parts)


EDGE_VARIANTS = {
    "E0": EdgePromptVariant(
        variant_id="E0",
        preamble=make_preamble(
            """You are a factual-memo agent.

- Do not propose refactorings.
- Do not assess difficulty, risk, or whether this edge is good or bad to break.
- Focus on preserving concrete facts that may matter for later agents.""",
            EDGE_SHARED_FACTUAL_CORE,
        ),
    ),

    "E1": EdgePromptVariant(
        variant_id="E1",
        preamble=make_preamble(
            """You are a candidate-edge analysis agent.

- You may cautiously note facts that could make this edge more or less attractive to inspect as a candidate to break later, but do not turn that into a full recommendation or plan.
- Keep the memo grounded in code facts, not architectural storytelling.""",
            EDGE_SHARED_FACTUAL_CORE,
        ),
    ),

    "E2": EdgePromptVariant(
        variant_id="E2",
        preamble=make_preamble(
            """You are a refactoring-direction analysis agent.

- In addition to the code-grounded edge analysis, you may cautiously mention 1-2 plausible refactoring directions for this edge, but only when strongly supported by the code.
- Keep any such suggestions grounded, and clearly tentative.
- Do not overcommit. If the code is not clear enough, say so.
- Prefer minimal meaningful architectural changes over hacky indirection.""",
            EDGE_SHARED_FACTUAL_CORE,
        ),
    ),
}


def require_edge_variant(variant_id: str) -> EdgePromptVariant:
    v = EDGE_VARIANTS.get((variant_id or "").strip())
    if v is None:
        raise ValueError(f"edge_variant must be one of {sorted(EDGE_VARIANTS.keys())} (got {variant_id!r})")
    return v