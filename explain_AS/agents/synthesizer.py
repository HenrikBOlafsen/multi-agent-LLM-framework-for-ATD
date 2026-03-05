# explain_AS/agents/synthesizer.py
from __future__ import annotations

from typing import List, Sequence

from agents.prompts.prompts_synthesizer import require_synthesizer_variant
from budgeting import (
    allocate_token_budgets_even_share_with_redistribution,
    estimate_tokens_from_chars,
    estimate_tokens_from_text,
    tokens_to_chars,
)
from context import cycle_chain_str, format_block_for_prompt, prompt_block_wrapper_len, require_language
from language import edge_semantics_text
from llm import Agent, LLMClient


SYNTHESIZER_MIN_OUTPUT_TOKENS_RESERVED = 3334  # previously ~10k chars at 3 chars/token
SYNTHESIZER_SAFETY_MARGIN_TOKENS = 1000


def build_synthesizer_user_prompt(
    *,
    client: LLMClient,
    language: str,
    cycle_nodes: List[str],
    edge_reports: Sequence[str],
    aux_context: str,
    synthesizer_variant_id: str,
) -> str:
    language = require_language(language)
    synthesizer_prompt_variant = require_synthesizer_variant(synthesizer_variant_id)

    semantics = edge_semantics_text(language)
    cycle_chain = cycle_chain_str(cycle_nodes)

    prompt_prefix = f"""{synthesizer_prompt_variant.preamble}

---

{semantics}

Cycle:
{cycle_chain}

Edge reports (in cycle order, may be truncated):
""".rstrip() + "\n"

    prompt_suffix = f"\n\n{synthesizer_prompt_variant.output_headings}\n"

    normalized_edge_reports = [str(report or "").strip() or "N/A" for report in (edge_reports or [])]

    # Only include aux section if we actually have aux context.
    has_aux = bool(str(aux_context or "").strip())
    normalized_aux_text = str(aux_context or "").strip()

    aux_separator = "\n\nOptional additional context (may be truncated):\n" if has_aux else ""

    overhead_tokens_estimate = estimate_tokens_from_text(prompt_prefix + aux_separator + prompt_suffix)

    total_input_tokens_budget = (
        int(client.context_length)
        - int(SYNTHESIZER_SAFETY_MARGIN_TOKENS)
        - int(SYNTHESIZER_MIN_OUTPUT_TOKENS_RESERVED)
        - int(overhead_tokens_estimate)
    )
    total_input_tokens_budget = max(0, int(total_input_tokens_budget))

    # Budget items: one wrapped block per edge report, plus optional aux block.
    budget_item_needs_tokens: List[int] = []
    block_ids: List[str] = []

    for i, report_text in enumerate(normalized_edge_reports, start=1):
        block_id = f"Edge report {i}"
        need = estimate_tokens_from_text(report_text) + estimate_tokens_from_chars(prompt_block_wrapper_len(block_id))
        budget_item_needs_tokens.append(int(need))
        block_ids.append(block_id)

    if has_aux:
        aux_block_id = "Auxiliary report"
        need = estimate_tokens_from_text(normalized_aux_text) + estimate_tokens_from_chars(prompt_block_wrapper_len(aux_block_id))
        budget_item_needs_tokens.append(int(need))
        block_ids.append(aux_block_id)

    budget_item_allocations_tokens = allocate_token_budgets_even_share_with_redistribution(
        item_token_needs=budget_item_needs_tokens,
        total_tokens=int(total_input_tokens_budget),
    )

    rendered_blocks: List[str] = []
    for idx, (block_id, text, allocated_tokens) in enumerate(
        zip(block_ids, (normalized_edge_reports + ([normalized_aux_text] if has_aux else [])), budget_item_allocations_tokens),
        start=1,
    ):
        _ = idx  # kept for readability if needed later
        allocated_chars_total = max(1, tokens_to_chars(int(allocated_tokens))) if allocated_tokens > 0 else 1
        block, _was_truncated = format_block_for_prompt(
            repo_rel_path=block_id,
            block_text=text,
            max_chars=int(allocated_chars_total),
        )
        rendered_blocks.append(block.strip())

    # Split the section so aux keeps its separator heading.
    if has_aux:
        edge_blocks = rendered_blocks[: len(normalized_edge_reports)]
        aux_block = rendered_blocks[-1] if rendered_blocks else ""
        edges_section = "\n\n".join([b for b in edge_blocks if b.strip()]).strip() or "N/A"
        return (prompt_prefix + edges_section + aux_separator + aux_block + prompt_suffix).strip() + "\n"

    edges_section = "\n\n".join([b for b in rendered_blocks if b.strip()]).strip() or "N/A"
    return (prompt_prefix + edges_section + prompt_suffix).strip() + "\n"


def run_synthesizer_agent(
    *,
    client: LLMClient,
    transcript_path: str,
    language: str,
    cycle_nodes: List[str],
    edge_reports: Sequence[str],
    aux_context: str = "",
    synthesizer_variant_id: str = "S0",
) -> str:
    language = require_language(language)

    synthesizer_agent = Agent(name="synthesizer")

    user_prompt = build_synthesizer_user_prompt(
        client=client,
        language=language,
        cycle_nodes=cycle_nodes,
        edge_reports=edge_reports,
        aux_context=aux_context,
        synthesizer_variant_id=synthesizer_variant_id,
    )

    return synthesizer_agent.ask(
        client=client,
        transcript_path=transcript_path,
        user_prompt=user_prompt,
        min_output_tokens_reserved=int(SYNTHESIZER_MIN_OUTPUT_TOKENS_RESERVED),
        safety_margin_tokens=int(SYNTHESIZER_SAFETY_MARGIN_TOKENS),
        max_output_chars_soft=None,
    )