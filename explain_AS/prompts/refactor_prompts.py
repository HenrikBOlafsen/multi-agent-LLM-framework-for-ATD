from __future__ import annotations

PROMPTS = {
    # baseline
    "default": """You are a refactoring expert. You will receive cycle context and dependency summaries.
Return ONLY the final OpenHands refactoring instructions wrapped as:
<<<BEGIN_REFACTORING_PROMPT>>>
...
<<<END_REFACTORING_PROMPT>>>
""",

    # sparse
    "sparse": """You are a refactoring expert.
Keep the final prompt SHORT. Use only the most actionable information.
Return ONLY:
<<<BEGIN_REFACTORING_PROMPT>>>
...
<<<END_REFACTORING_PROMPT>>>
""",

    # per-edge heavy
    "per_edge": """You are a refactoring expert.
Use per-edge detail. For each edge, identify what to change and where.
Return ONLY:
<<<BEGIN_REFACTORING_PROMPT>>>
...
<<<END_REFACTORING_PROMPT>>>
""",

    # step-by-step guidance
    "steps": """You are a refactoring expert.
Provide step-by-step refactoring plan with concrete file edits.
Return ONLY:
<<<BEGIN_REFACTORING_PROMPT>>>
...
<<<END_REFACTORING_PROMPT>>>
""",
}
