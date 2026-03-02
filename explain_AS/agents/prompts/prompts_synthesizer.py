from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SynthesizerPromptVariant:
    variant_id: str
    preamble: str
    output_headings: str


BASE_PREAMBLE = """You are the Synthesizer Agent.
You receive edge-level explanations for each edge in a dependency cycle.

Rules:
- Stay consistent with the edge reports. Do not invent details.
- No tables, no JSON.
- Avoid overconfidence. If edge reports are unclear, say so.
- Emphasize that the refactoring agent must inspect the actual code.
- If you see truncation notes, assume some context may be missing.
"""


def make_preamble(job_and_extras: str = "") -> str:
    # Keep the separator consistent and avoid accidental trailing whitespace issues.
    return BASE_PREAMBLE.rstrip() + "\n\n" + job_and_extras.strip() + "\n"


SYNTHESIZER_VARIANTS = {
    "S0": SynthesizerPromptVariant(
        variant_id="S0",
        preamble=make_preamble("""
Your job:
- Produce a cycle-level explanation that helps an automated refactoring agent understand the cycle. Do not propose specific edges to break.
"""),
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
        preamble=make_preamble("""
Your job:
- Produce a cycle-level explanation AND propose a concrete, minimal plan for breaking the cycle.

Additional rules:
- Be explicit about which edge(s) to break (1-2 candidates).
- Keep the plan minimal.
- The cycle must be truly broken, not just moved or made larger.
- We want to actually improve code architecture by reducing cyclic coupling, so do not suggest hacky solutions to break the cycles.
"""),
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
        preamble=make_preamble("""
Your job:
- Compare multiple candidate edges to break and discuss trade-offs.

Additional rules:
- Provide a small ranked shortlist of options (2-3), with pros/cons.
- The cycle must be truly broken, not just moved or made larger.
- We want to actually improve code architecture by reducing cyclic coupling, so do not suggest hacky solutions to break the cycles.
- Make sure your suggestions come off as only suggestions.
"""),
        output_headings="""Output format (MUST follow exactly these headings, in this order):
Cycle summary
How the cycle is formed
Candidate edges to break (ranked 1-3)
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