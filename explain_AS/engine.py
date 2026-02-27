from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agents.boundary import SCCEdge, run_boundary_agent
from agents.edge import Edge, run_edge_agent
from agents.graph import run_graph_agent
from agents.review import run_review_agent
from agents.synthesizer import run_synthesizer_agent
from context import filtered_cycle_nodes, read_cycle_files, require_language
from llm import LLMClient
from minimal_prompt import build_minimal_prompt


@dataclass(frozen=True)
class ExplainEngineResult:
    cycle_nodes: List[str]
    final_prompt_text: str  # written to prompt.txt


def _parse_scc_id_from_cycle_id(cycle_id: str) -> Optional[str]:
    """
    cycle ids look like: "scc_3_cycle_17"
    """
    s = str(cycle_id or "")
    if s.startswith("scc_") and "_cycle_" in s:
        return s.split("_cycle_", 1)[0]
    return None


def _build_scc_text_from_report(scc_report: Dict[str, Any], scc_id: str) -> str:
    for scc in (scc_report.get("sccs") or []):
        if str(scc.get("id")) != scc_id:
            continue

        nodes = [str(n.get("id")) for n in (scc.get("nodes") or []) if isinstance(n, dict)]
        edges = scc.get("edges") or []

        lines: List[str] = []
        lines.append(f"SCC id: {scc_id}")
        lines.append("")
        lines.append("Nodes:")
        for n in nodes:
            lines.append(f"- {n}")

        lines.append("")
        lines.append("Edges:")
        for e in edges:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or "")
            tgt = str(e.get("target") or "")
            if src and tgt:
                lines.append(f"- {src} -> {tgt}")

        return "\n".join(lines).strip()

    return ""


def _extract_scc_edges_from_report(scc_report: Dict[str, Any], scc_id: str) -> List[SCCEdge]:
    edges_out: List[SCCEdge] = []
    for scc in (scc_report.get("sccs") or []):
        if str(scc.get("id")) != scc_id:
            continue
        edges = scc.get("edges") or []
        for e in edges:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or "")
            tgt = str(e.get("target") or "")
            if src and tgt:
                edges_out.append(SCCEdge(source=src, target=tgt))
        break
    return edges_out


def _get_auxiliary_agent(params: Dict[str, Any]) -> str:
    """
    Config:
      params["auxiliary_agent"] in {"none","boundary","graph","review"}
    """
    aux = str(params.get("auxiliary_agent") or "none").strip().lower()
    if aux not in {"none", "boundary", "graph", "review"}:
        raise ValueError(f"auxiliary_agent must be one of none|boundary|graph|review (got {aux!r})")
    return aux


def _run_minimal(*, cycle: Dict[str, Any], language: str) -> ExplainEngineResult:
    cycle_nodes = filtered_cycle_nodes([str(n) for n in (cycle.get("nodes") or [])], skip_init=True)
    prompt = build_minimal_prompt(cycle_nodes, language)
    return ExplainEngineResult(cycle_nodes=cycle_nodes, final_prompt_text=prompt)


def _run_multi_agent(
    *,
    client: LLMClient,
    transcript_path: str,
    repo_root: str,
    language: str,
    cycle: Dict[str, Any],
    scc_report: Dict[str, Any],
    params: Dict[str, Any],
) -> ExplainEngineResult:
    """
    OUTPUT POLICY:
      prompt.txt contains ONLY:
        1) the minimal base prompt, AND
        2) the final cycle-level explanation (synthesizer output, or reviewer output)

      It does NOT include per-edge reports or auxiliary agent output as appendices.
    """
    language = require_language(language)

    edge_variant_id = str(params.get("edge_variant") or "E0").strip()
    synthesizer_variant_id = str(params.get("synthesizer_variant") or "S0").strip()
    auxiliary_agent = _get_auxiliary_agent(params)

    raw_nodes = [str(n) for n in (cycle.get("nodes") or [])]
    cycle_nodes = filtered_cycle_nodes(raw_nodes, skip_init=True)

    raw_edges = list(cycle.get("edges") or [])
    filtered_edges: List[Edge] = []
    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        a = str(e.get("source") or "")
        b = str(e.get("target") or "")
        if not a or not b:
            continue
        if a not in cycle_nodes or b not in cycle_nodes:
            continue
        filtered_edges.append(Edge(a=a, b=b))

    files_by_node = read_cycle_files(repo_root=repo_root, cycle_nodes=cycle_nodes, skip_init=True)

    # Edge agents still run (needed for synthesizer/reviewer), but their outputs are NOT written to prompt.txt.
    edge_reports: List[str] = []
    for edge in filtered_edges:
        report = run_edge_agent(
            client=client,
            transcript_path=transcript_path,
            language=language,
            cycle_nodes=cycle_nodes,
            edge=edge,
            files_by_node=files_by_node,
            edge_variant_id=edge_variant_id,
        )
        edge_reports.append(report)

    # Optional auxiliary context used only as synthesizer/reviewer input (not output).
    aux_context = ""
    if auxiliary_agent == "boundary":
        cycle_id = str(cycle.get("id") or "")
        scc_id = _parse_scc_id_from_cycle_id(cycle_id) or ""
        scc_edges: List[SCCEdge] = _extract_scc_edges_from_report(scc_report, scc_id) if scc_id else []

        boundary_text = run_boundary_agent(
            client=client,
            transcript_path=transcript_path,
            language=language,
            cycle_nodes=cycle_nodes,
            scc_edges=scc_edges,
        )
        aux_context = "=== Boundary heuristic agent ===\n" + boundary_text.strip()

    elif auxiliary_agent == "graph":
        cycle_id = str(cycle.get("id") or "")
        scc_id = _parse_scc_id_from_cycle_id(cycle_id) or ""
        scc_text = _build_scc_text_from_report(scc_report, scc_id) if scc_id else ""
        graph_text = run_graph_agent(
            client=client,
            transcript_path=transcript_path,
            language=language,
            cycle_nodes=cycle_nodes,
            scc_text=scc_text,
        )
        aux_context = "=== Structural context agent ===\n" + graph_text.strip()

    synthesizer_text = run_synthesizer_agent(
        client=client,
        transcript_path=transcript_path,
        language=language,
        cycle_nodes=cycle_nodes,
        edge_reports=edge_reports,
        aux_context=aux_context,
        synthesizer_variant_id=synthesizer_variant_id,
    ).strip()

    # Review-mode: reviewer output replaces synthesizer output verbatim (no parsing).
    if auxiliary_agent == "review":
        reviewer_text = run_review_agent(
            client=client,
            transcript_path=transcript_path,
            language=language,
            cycle_nodes=cycle_nodes,
            edge_reports=edge_reports,
            synthesizer_text=synthesizer_text,
            aux_context=aux_context,
        ).strip()
        synthesizer_text = reviewer_text or synthesizer_text

    minimal = build_minimal_prompt(cycle_nodes, language)

    # Final prompt: minimal base + final cycle-level explanation only.
    final_prompt = (minimal.rstrip() + "\n\n" + synthesizer_text.strip()).rstrip() + "\n"
    return ExplainEngineResult(cycle_nodes=cycle_nodes, final_prompt_text=final_prompt)


def run_explain_engine(
    *,
    client: LLMClient,
    transcript_path: str,
    repo_root: str,
    language: str,
    cycle: Dict[str, Any],
    scc_report: Dict[str, Any],
    params: Dict[str, Any],
) -> ExplainEngineResult:
    language = require_language(language)

    orchestrator_id = str(params.get("orchestrator") or "multi_agent").strip()
    if orchestrator_id not in {"minimal", "multi_agent"}:
        raise ValueError("orchestrator must be 'minimal' or 'multi_agent'")

    if orchestrator_id == "minimal":
        return _run_minimal(cycle=cycle, language=language)

    return _run_multi_agent(
        client=client,
        transcript_path=transcript_path,
        repo_root=repo_root,
        language=language,
        cycle=cycle,
        scc_report=scc_report,
        params=params,
    )