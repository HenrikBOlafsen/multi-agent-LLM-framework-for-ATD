from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SynthesizerPromptVariant:
    variant_id: str
    preamble: str


BASE_PREAMBLE = """You are the Synthesizer Agent.
You receive edge-level reports for each edge in a dependency cycle.

Your job is to produce a cycle-level memo for a later refactoring agent.

Rules:
- Stay consistent with the edge reports. Do not invent details.
- If edge reports are unclear, say so.
- Emphasize that the refactoring agent must inspect the actual code.
- If you see truncation notes, assume some context may be missing.
- No tables, no JSON.
- Avoid generic architectural storytelling.
- Preserve concrete facts and recurring patterns from the edge reports.
- Treat edge reports as the primary source of truth.
""".strip()


SYNTHESIZER_SHARED_FACTUAL_CORE = """- Preserve, when supported by the edge reports:
  - how the cycle is formed,
  - the most important edge facts,
  - recurring patterns across edges,
  - what should still be verified in the real code,
  - and any important uncertainty or missing context.
- Keep the memo useful for a later agent that will inspect and modify the real code.
""".strip()


def make_preamble(*parts: str) -> str:
    cleaned_parts = [p.strip() for p in parts if str(p or "").strip()]
    if not cleaned_parts:
        return BASE_PREAMBLE
    return BASE_PREAMBLE + "\n\nAdditional rules:\n" + "\n\n".join(cleaned_parts)


SYNTHESIZER_VARIANTS = {
    "S0": SynthesizerPromptVariant(
        variant_id="S0",
        preamble=make_preamble(
            """You are a factual-memo synthesizer.

- Do not propose specific edges to break.
- Do not give a refactoring plan.
- Produce a factual cycle-level memo.""",
            SYNTHESIZER_SHARED_FACTUAL_CORE,
        ),
    ),

    "S1": SynthesizerPromptVariant(
        variant_id="S1",
        preamble=make_preamble(
            """You are a candidate-edge synthesizer.

- You may also suggest 1-2 candidate edges to inspect first.
- Keep candidate suggestions cautious and grounded in the edge reports.
- Do not give a full refactoring plan.
- Do not overclaim that a candidate will definitely work.
- Preserve the concrete facts behind the suggestions, not just the suggestions themselves.""",
            SYNTHESIZER_SHARED_FACTUAL_CORE,
        ),
    ),

    "S2": SynthesizerPromptVariant(
        variant_id="S2",
        preamble=make_preamble(
            """You are a refactoring-direction synthesizer.

- You may also suggest a cautious concrete refactoring direction.
- Keep it grounded in the edge reports.
- Prefer a minimal meaningful architectural change rather than hacky indirection.
- Do not overclaim that the plan will definitely succeed.
- Make clear what still needs to be checked in the real code.""",
            SYNTHESIZER_SHARED_FACTUAL_CORE,
        ),
    ),
}


def require_synthesizer_variant(variant_id: str) -> SynthesizerPromptVariant:
    v = SYNTHESIZER_VARIANTS.get((variant_id or "").strip())
    if v is None:
        raise ValueError(
            f"synthesizer_variant must be one of {sorted(SYNTHESIZER_VARIANTS.keys())} (got {variant_id!r})"
        )
    return v