from __future__ import annotations

from typing import List

from budgeting import estimate_tokens_from_text, tokens_to_chars
from context import format_block_for_prompt, cycle_chain_str, require_language
from language import edge_semantics_text
from llm import Agent, LLMClient


GRAPH_MIN_OUTPUT_TOKENS_RESERVED = 2000
GRAPH_SAFETY_MARGIN_TOKENS = 1000


GRAPH_PROMPT_PREAMBLE = """You are the Structural Context Agent.
You receive the cycle and SCC graph context as plain text (nodes and edges).
Your job is to summarize how the cycle sits within the SCC.

Rules:
- Stay factual based on provided SCC text.
- No tables, no JSON.
- Keep it short and focused.
- If you see truncation notes, assume some context may be missing.
""".strip()


def build_graph_user_prompt(
    *,
    language: str,
    cycle_nodes: List[str],
    scc_text: str,
    context_length: int,
) -> str:
    semantics = edge_semantics_text(language)
    chain = cycle_chain_str(cycle_nodes)
    normalized_scc_text = scc_text.strip() or "N/A"

    prompt_prefix = f"""{GRAPH_PROMPT_PREAMBLE}

---

{semantics}

Cycle:
{chain}

SCC context (nodes + edges):
"""
    prompt_suffix = """

Output format (MUST follow exactly these headings, in this order):
How the cycle sits in the SCC
Hubs / bridges (if any)
External connections (if visible)
Risks when breaking edges
Notes / uncertainty
""".lstrip()

    overhead_tokens_estimate = estimate_tokens_from_text(prompt_prefix + prompt_suffix)
    total_input_tokens_budget = (
        int(context_length)
        - int(GRAPH_SAFETY_MARGIN_TOKENS)
        - int(GRAPH_MIN_OUTPUT_TOKENS_RESERVED)
        - int(overhead_tokens_estimate)
    )
    total_input_tokens_budget = max(0, int(total_input_tokens_budget))

    scc_block_char_budget = max(1, tokens_to_chars(int(total_input_tokens_budget))) if total_input_tokens_budget > 0 else 1
    scc_block, _scc_truncated = format_block_for_prompt(
        label="SCC context",
        repo_rel_path="SCC_CONTEXT.txt",
        block_text=normalized_scc_text,
        max_chars=int(scc_block_char_budget),
    )

    return (prompt_prefix + scc_block + "\n" + prompt_suffix).strip() + "\n"


def run_graph_agent(
    *,
    client: LLMClient,
    transcript_path: str,
    language: str,
    cycle_nodes: List[str],
    scc_text: str,
) -> str:
    language = require_language(language)
    graph_agent = Agent(name="graph")

    user_prompt = build_graph_user_prompt(
        language=language,
        cycle_nodes=cycle_nodes,
        scc_text=scc_text,
        context_length=int(client.context_length),
    )

    return graph_agent.ask(
        client=client,
        transcript_path=transcript_path,
        user_prompt=user_prompt,
        min_output_tokens_reserved=int(GRAPH_MIN_OUTPUT_TOKENS_RESERVED),
        safety_margin_tokens=int(GRAPH_SAFETY_MARGIN_TOKENS),
        max_output_chars_soft=None,
    )