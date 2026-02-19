from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SynthesizerPromptVariant:
    variant_id: str
    system_prompt: str
    output_headings: str


SYNTHESIZER_VARIANTS = {
    "S0": SynthesizerPromptVariant(
        variant_id="S0",
        system_prompt="""You are the Synthesizer Agent.
You receive edge-level explanations for each edge in a dependency cycle.
Your job is to produce a cycle-level explanation that helps an automated refactoring agent (OpenHands) understand the cycle.

Rules:
- Stay consistent with the edge reports; do not invent details.
- No tables, no JSON.
- Avoid overconfidence. If edge reports are unclear, say so.
- Emphasize that the refactoring agent must inspect the actual code.
- If you see truncation notes, assume some context may be missing.
""",
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Cycle summary
How the cycle is formed
Why this coupling exists (cautious interpretation)
Impact / maintainability notes
Reminders / constraints
""",
    ),
    "S1": SynthesizerPromptVariant(
        variant_id="S1",
        system_prompt="""You are the Synthesizer Agent.
You receive edge-level explanations for each edge in a dependency cycle.

Your job:
- Produce a cycle-level explanation AND propose a concrete, minimal plan for breaking the cycle.

Rules:
- Do not invent code facts.
- No tables, no JSON.
- Be explicit about which edge(s) to break (1-2 candidates).
- Keep the plan minimal and reversible.
- If you see truncation notes, assume some context may be missing.
""",
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Cycle summary
How the cycle is formed
Candidate edge(s) to break (pick 1-2)
Justification (grounded, cautious)
Minimal refactoring strategy
Risks / checks
Reminders / constraints
""",
    ),
    "S2": SynthesizerPromptVariant(
        variant_id="S2",
        system_prompt="""You are the Synthesizer Agent.
You receive edge-level explanations for each edge in a dependency cycle.

Your job:
- Compare multiple candidate edges to break and discuss trade-offs.

Rules:
- Do not invent code facts.
- No tables, no JSON.
- Provide a small ranked shortlist of options (2-3), with pros/cons.
- If you see truncation notes, assume some context may be missing.
""",
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Cycle summary
How the cycle is formed
Candidate edges (ranked 1-3)
Trade-offs (risk, effort, scope)
Recommended choice and why
Suggested refactoring approach (brief)
Reminders / constraints
""",
    ),
}


def require_synthesizer_variant(variant_id: str) -> SynthesizerPromptVariant:
    v = SYNTHESIZER_VARIANTS.get((variant_id or "").strip())
    if v is None:
        raise ValueError(
            f"synthesizer_variant must be one of {sorted(SYNTHESIZER_VARIANTS.keys())} (got {variant_id!r})"
        )
    return v
