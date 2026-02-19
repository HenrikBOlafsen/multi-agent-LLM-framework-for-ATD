from __future__ import annotations

from typing import List

from context import cycle_chain_str, require_language
from language import edge_semantics_text
from llm import Agent, LLMClient


BOUNDARY_MIN_OUTPUT_TOKENS_RESERVED = 2000
BOUNDARY_SAFETY_MARGIN_TOKENS = 1000


BOUNDARY_SYSTEM_PROMPT = """You are the Boundary Heuristic Agent.
You infer likely architectural boundaries from file paths and naming only.

Rules:
- Be cautious: do not assume frameworks.
- No tables, no JSON.
- Keep it short and helpful.
- If you see truncation notes, assume some context may be missing.
"""


def build_boundary_user_prompt(*, language: str, cycle_nodes: List[str]) -> str:
    semantics = edge_semantics_text(language)
    chain = cycle_chain_str(cycle_nodes)
    nodes_block = "\n".join([f"- {n}" for n in cycle_nodes]) if cycle_nodes else "N/A"

    return f"""{semantics}

Cycle:
{chain}

Files in cycle:
{nodes_block}

Output format (MUST follow exactly these headings):
Likely boundaries
Possible boundary violations (if any)
Notes / uncertainty
"""


def run_boundary_agent(
    *,
    client: LLMClient,
    transcript_path: str,
    language: str,
    cycle_nodes: List[str],
) -> str:
    language = require_language(language)
    boundary_agent = Agent(name="boundary", system_prompt=BOUNDARY_SYSTEM_PROMPT)
    user_prompt = build_boundary_user_prompt(language=language, cycle_nodes=cycle_nodes)

    return boundary_agent.ask(
        client=client,
        transcript_path=transcript_path,
        user_prompt=user_prompt,
        min_output_tokens_reserved=int(BOUNDARY_MIN_OUTPUT_TOKENS_RESERVED),
        safety_margin_tokens=int(BOUNDARY_SAFETY_MARGIN_TOKENS),
        max_output_chars_soft=None,
    )
