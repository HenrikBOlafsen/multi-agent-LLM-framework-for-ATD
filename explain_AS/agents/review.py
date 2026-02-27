from __future__ import annotations

from typing import List, Sequence

from budgeting import (
    allocate_token_budgets_even_share_with_redistribution,
    estimate_tokens_from_text,
    tokens_to_chars,
)
from context import cycle_chain_str, format_block_for_prompt, require_language
from language import edge_semantics_text
from llm import Agent, LLMClient


REVIEW_MIN_OUTPUT_TOKENS_RESERVED = 3667
REVIEW_SAFETY_MARGIN_TOKENS = 1000


REVIEW_PROMPT_PREAMBLE = """You are the Reviewer Agent.
You are a finalizer: rewrite the synthesizer output to be clearer and internally consistent.

Hard rules:
- Do NOT add new facts.
- Do NOT include meta commentary, critiques, or headings like "Issues found" or "Suggested revisions".
- Output ONLY the final revised cycle explanation, in the requested output format.
- No tables, no JSON.
- If you see truncation notes, assume some context may be missing.
""".strip()


def build_review_user_prompt(
    *,
    language: str,
    cycle_nodes: List[str],
    synthesizer_text: str,
    edge_reports: Sequence[str],
    aux_context: str,
    context_length: int,
) -> str:
    semantics = edge_semantics_text(language)
    cycle_chain = cycle_chain_str(cycle_nodes)

    prompt_prefix = f"""{REVIEW_PROMPT_PREAMBLE}

---

{semantics}

Cycle:
{cycle_chain}

Synthesizer output (rewrite for clarity/consistency; do not add facts):
""".rstrip() + "\n"

    evidence_separator = "\n\nAdditional evidence (edge reports and aux context, may be truncated):\n"

    prompt_suffix = """

Output format (MUST follow exactly these headings, in this order):
Cycle summary
How the cycle is formed
Why this coupling exists (cautious interpretation)
Impact / maintainability notes
Reminders / constraints
""".lstrip()

    normalized_synthesizer_text = (synthesizer_text or "").strip() or "N/A"
    normalized_edge_reports = [str(report or "").strip() or "N/A" for report in (edge_reports or [])]
    normalized_aux_text = (aux_context or "").strip() or "None."

    overhead_tokens_estimate = estimate_tokens_from_text(prompt_prefix + evidence_separator + prompt_suffix)

    total_input_tokens_budget = (
        int(context_length)
        - int(REVIEW_SAFETY_MARGIN_TOKENS)
        - int(REVIEW_MIN_OUTPUT_TOKENS_RESERVED)
        - int(overhead_tokens_estimate)
    )
    total_input_tokens_budget = max(0, int(total_input_tokens_budget))

    # Priority:
    # 1) allocate as much as possible to synthesizer output
    # 2) remaining shared across edge reports + aux context
    synthesizer_tokens_needed = estimate_tokens_from_text(normalized_synthesizer_text)
    synthesizer_tokens_allocated = min(int(synthesizer_tokens_needed), int(total_input_tokens_budget))
    remaining_tokens_for_evidence = max(0, int(total_input_tokens_budget) - int(synthesizer_tokens_allocated))

    synthesizer_chars_budget = (
        max(1, tokens_to_chars(int(synthesizer_tokens_allocated))) if synthesizer_tokens_allocated > 0 else 1
    )
    synthesizer_block, _synth_truncated = format_block_for_prompt(
        label="Synthesizer output",
        repo_rel_path="SYNTHESIZER_OUTPUT.txt",
        block_text=normalized_synthesizer_text,
        max_chars=int(synthesizer_chars_budget),
    )

    evidence_items = normalized_edge_reports + [normalized_aux_text]
    evidence_needs_tokens = [estimate_tokens_from_text(text) for text in evidence_items]
    evidence_allocations_tokens = allocate_token_budgets_even_share_with_redistribution(
        item_token_needs=evidence_needs_tokens,
        total_tokens=int(remaining_tokens_for_evidence),
    )

    rendered_edge_blocks: List[str] = []
    for index, (edge_report_text, allocated_tokens) in enumerate(
        zip(normalized_edge_reports, evidence_allocations_tokens[: len(normalized_edge_reports)]), start=1
    ):
        allocated_chars = max(1, tokens_to_chars(int(allocated_tokens))) if allocated_tokens > 0 else 1
        edge_block, _edge_truncated = format_block_for_prompt(
            label=f"Edge report {index}",
            repo_rel_path=f"EDGE_REPORT_{index}.txt",
            block_text=edge_report_text,
            max_chars=int(allocated_chars),
        )
        rendered_edge_blocks.append(edge_block)

    aux_allocated_tokens = evidence_allocations_tokens[-1] if evidence_allocations_tokens else 0
    aux_allocated_chars = max(1, tokens_to_chars(int(aux_allocated_tokens))) if aux_allocated_tokens > 0 else 1
    aux_block, _aux_truncated = format_block_for_prompt(
        label="Aux context",
        repo_rel_path="AUX_CONTEXT.txt",
        block_text=normalized_aux_text,
        max_chars=int(aux_allocated_chars),
    )

    evidence_section = "\n\n".join([b for b in (rendered_edge_blocks + [aux_block]) if b.strip()]).strip() or "N/A"
    return (prompt_prefix + synthesizer_block + evidence_separator + evidence_section + "\n" + prompt_suffix).strip() + "\n"


def run_review_agent(
    *,
    client: LLMClient,
    transcript_path: str,
    language: str,
    cycle_nodes: List[str],
    edge_reports: Sequence[str],
    synthesizer_text: str,
    aux_context: str = "",
) -> str:
    language = require_language(language)
    review_agent = Agent(name="review")

    user_prompt = build_review_user_prompt(
        language=language,
        cycle_nodes=cycle_nodes,
        synthesizer_text=synthesizer_text,
        edge_reports=edge_reports,
        aux_context=aux_context,
        context_length=int(client.context_length),
    )

    return review_agent.ask(
        client=client,
        transcript_path=transcript_path,
        user_prompt=user_prompt,
        min_output_tokens_reserved=int(REVIEW_MIN_OUTPUT_TOKENS_RESERVED),
        safety_margin_tokens=int(REVIEW_SAFETY_MARGIN_TOKENS),
        max_output_chars_soft=None,
    )