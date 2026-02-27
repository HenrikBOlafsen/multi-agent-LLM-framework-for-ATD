from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from budgeting import estimate_tokens_from_text, tokens_to_chars
from context import cycle_chain_str, format_block_for_prompt, require_language
from language import edge_semantics_text
from llm import Agent, LLMClient


BOUNDARY_MIN_OUTPUT_TOKENS_RESERVED = 2000
BOUNDARY_SAFETY_MARGIN_TOKENS = 1000

# Budget knobs for the external connections block
BOUNDARY_MAX_SAMPLES_PER_DIR = 8
BOUNDARY_MAX_FOLDER_BUCKETS_PER_DIR = 6
BOUNDARY_FOLDER_BUCKET_DEPTH = 2


BOUNDARY_PROMPT_PREAMBLE = """You are the Boundary Heuristic Agent.
You infer likely architectural boundaries from file paths and naming only.

Rules:
- Be cautious: do not assume frameworks.
- No tables, no JSON.
- Keep it short and helpful.
- If you see truncation notes, assume some context may be missing.
""".strip()


@dataclass(frozen=True)
class SCCEdge:
    source: str
    target: str


def _norm_path(p: str) -> str:
    return (p or "").replace("\\", "/").strip()


def _folder_bucket(path: str, *, depth: int) -> str:
    """
    Bucket by the first N folder segments (excluding the filename).
    Example (depth=2):
      src/domain/user.py -> src/domain
      user.py -> (root)
    """
    p = _norm_path(path).strip("/")
    parts = [x for x in p.split("/") if x]
    if len(parts) <= 1:
        return "(root)"
    # exclude filename from bucket depth calculation
    max_folder_parts = max(1, len(parts) - 1)
    take = min(int(depth), max_folder_parts)
    return "/".join(parts[:take])


def _summarize_paths(
    paths: Sequence[str],
    *,
    folder_depth: int,
    max_folders: int,
    max_samples: int,
) -> Tuple[int, List[Tuple[str, int]], List[str], int, int]:
    """
    Returns:
      total,
      folder_counts_top,
      samples,
      omitted_samples_count,
      omitted_folder_buckets_count
    """
    normalized = sorted({_norm_path(p) for p in (paths or []) if p and p.strip()})
    total = len(normalized)

    buckets = [_folder_bucket(p, depth=folder_depth) for p in normalized]
    c = Counter(buckets)
    all_folder_counts = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
    folder_counts_top = all_folder_counts[: max(0, int(max_folders))]
    omitted_folder_buckets = max(0, len(all_folder_counts) - len(folder_counts_top))

    samples = normalized[: max(0, int(max_samples))]
    omitted_samples = max(0, total - len(samples))

    return total, folder_counts_top, samples, omitted_samples, omitted_folder_buckets


def _build_adjacency(edges: Iterable[SCCEdge]) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    outgoing: Dict[str, Set[str]] = {}
    incoming: Dict[str, Set[str]] = {}

    for e in edges:
        src = _norm_path(e.source)
        tgt = _norm_path(e.target)
        if not src or not tgt:
            continue

        outgoing.setdefault(src, set()).add(tgt)
        incoming.setdefault(tgt, set()).add(src)

    return outgoing, incoming


def _render_external_connections_block(
    *,
    cycle_nodes: Sequence[str],
    scc_edges: Sequence[SCCEdge],
    folder_depth: int,
    max_folder_buckets_per_dir: int,
    max_samples_per_dir: int,
) -> str:
    pretty_cycle = [_norm_path(n) for n in (cycle_nodes or []) if n and n.strip()]
    cycle_set = set(pretty_cycle)
    if not pretty_cycle:
        return "N/A"

    outgoing, incoming = _build_adjacency(scc_edges or [])

    lines: List[str] = []
    for node in pretty_cycle:
        out_all = outgoing.get(node, set())
        in_all = incoming.get(node, set())

        out_ext = sorted([p for p in out_all if p not in cycle_set])
        in_ext = sorted([p for p in in_all if p not in cycle_set])

        out_total, out_folders, out_samples, out_omitted_samples, out_omitted_folders = _summarize_paths(
            out_ext,
            folder_depth=folder_depth,
            max_folders=max_folder_buckets_per_dir,
            max_samples=max_samples_per_dir,
        )
        in_total, in_folders, in_samples, in_omitted_samples, in_omitted_folders = _summarize_paths(
            in_ext,
            folder_depth=folder_depth,
            max_folders=max_folder_buckets_per_dir,
            max_samples=max_samples_per_dir,
        )

        lines.append(node)

        lines.append(f"- Outgoing outside-cycle: {out_total} total")
        if out_total <= 0:
            lines.append("  - (none)")
        else:
            if out_folders:
                folder_str = ", ".join([f"{k} ({v})" for k, v in out_folders])
                suffix = f", ... +{out_omitted_folders} more buckets" if out_omitted_folders else ""
                lines.append(f"  - By folder: {folder_str}{suffix}")
            lines.append("  - Samples:")
            lines.extend([f"    - {p}" for p in out_samples])
            if out_omitted_samples:
                lines.append(f"    - ... +{out_omitted_samples} more")

        lines.append(f"- Incoming outside-cycle: {in_total} total")
        if in_total <= 0:
            lines.append("  - (none)")
        else:
            if in_folders:
                folder_str = ", ".join([f"{k} ({v})" for k, v in in_folders])
                suffix = f", ... +{in_omitted_folders} more buckets" if in_omitted_folders else ""
                lines.append(f"  - By folder: {folder_str}{suffix}")
            lines.append("  - Samples:")
            lines.extend([f"    - {p}" for p in in_samples])
            if in_omitted_samples:
                lines.append(f"    - ... +{in_omitted_samples} more")

        lines.append("")  # spacer

    return "\n".join(lines).rstrip() or "N/A"


def build_boundary_user_prompt(
    *,
    language: str,
    cycle_nodes: List[str],
    scc_edges: List[SCCEdge],
    context_length: int,
) -> str:
    semantics = edge_semantics_text(language)
    chain = cycle_chain_str(cycle_nodes)

    external_raw = _render_external_connections_block(
        cycle_nodes=cycle_nodes,
        scc_edges=scc_edges,
        folder_depth=int(BOUNDARY_FOLDER_BUCKET_DEPTH),
        max_folder_buckets_per_dir=int(BOUNDARY_MAX_FOLDER_BUCKETS_PER_DIR),
        max_samples_per_dir=int(BOUNDARY_MAX_SAMPLES_PER_DIR),
    )

    prompt_prefix = f"""{BOUNDARY_PROMPT_PREAMBLE}

---

{semantics}

Cycle:
{chain}

External connections (outside-cycle), summarized per cycle file:
"""
    prompt_suffix = """

Output format (MUST follow exactly these headings):
Likely boundaries
Possible boundary violations (if any)
Notes / uncertainty
""".lstrip()

    overhead_tokens_estimate = estimate_tokens_from_text(prompt_prefix + prompt_suffix)
    total_input_tokens_budget = (
        int(context_length)
        - int(BOUNDARY_SAFETY_MARGIN_TOKENS)
        - int(BOUNDARY_MIN_OUTPUT_TOKENS_RESERVED)
        - int(overhead_tokens_estimate)
    )
    total_input_tokens_budget = max(0, int(total_input_tokens_budget))

    external_block_char_budget = (
        max(1, tokens_to_chars(int(total_input_tokens_budget))) if total_input_tokens_budget > 0 else 1
    )

    external_block, _external_truncated = format_block_for_prompt(
        label="Boundary external connections",
        repo_rel_path="BOUNDARY_EXTERNAL_CONNECTIONS.txt",
        block_text=(external_raw.strip() or "N/A"),
        max_chars=int(external_block_char_budget),
    )

    return (prompt_prefix + external_block + "\n" + prompt_suffix).strip() + "\n"


def run_boundary_agent(
    *,
    client: LLMClient,
    transcript_path: str,
    language: str,
    cycle_nodes: List[str],
    scc_edges: List[SCCEdge],
) -> str:
    language = require_language(language)
    boundary_agent = Agent(name="boundary")

    user_prompt = build_boundary_user_prompt(
        language=language,
        cycle_nodes=cycle_nodes,
        scc_edges=scc_edges,
        context_length=int(client.context_length),
    )

    return boundary_agent.ask(
        client=client,
        transcript_path=transcript_path,
        user_prompt=user_prompt,
        min_output_tokens_reserved=int(BOUNDARY_MIN_OUTPUT_TOKENS_RESERVED),
        safety_margin_tokens=int(BOUNDARY_SAFETY_MARGIN_TOKENS),
        max_output_chars_soft=None,
    )