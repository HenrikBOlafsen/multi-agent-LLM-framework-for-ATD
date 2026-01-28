from __future__ import annotations

from typing import Dict, Tuple

from agent_setup import log_section, log_line, Ansi
from agent_types.dependency_expert_A import DependencyExpertA
from agent_types.dependency_expert_B import DependencyExpertB
from agent_types.refactoring_expert import RefactoringExpert

from .base import OrchestratorBase, CycleContext, node_to_abs, extract_refactoring_prompt


class OrchestratorV2TwoStage(OrchestratorBase):
    """
    Stage1: A summarizes why A depends on B
    Stage2: B summarizes what in B is used by A
    Then directly ask RefactoringExpert using per-edge merged summaries (no CycleExpert).
    """

    def run(self, ctx: CycleContext, *, refactor_prompt_variant: str) -> str:
        log_section("OrchestratorV2TwoStage", "cyan")
        files = ctx.read_cycle_files()

        depA = DependencyExpertA("Dependency_Expert_A", self.client)
        depB = DependencyExpertB("Dependency_Expert_B", self.client)

        merged: Dict[str, Dict[str, str]] = {}  # edge_key -> {a_path,b_path, why, used}
        for i, e in enumerate(ctx.edges, 1):
            a_node, b_node = str(e["source"]), str(e["target"])
            a_path = node_to_abs(ctx.repo_root, a_node)
            b_path = node_to_abs(ctx.repo_root, b_node)
            log_line(f"[edge:{i}] {a_node} -> {b_node}", Ansi.DIM)

            why = depA.summarize_dependency(a_path, b_path, files[a_path])
            used = depB.summarize_dependency(a_path, b_path, files[b_path], why)

            merged[f"{a_path} -> {b_path}"] = {
                "a_path": a_path,
                "b_path": b_path,
                "why": why,
                "used": used,
            }

        ref = RefactoringExpert("Refactoring_Expert", self.client, prompt_variant=refactor_prompt_variant)

        # Let RefactoringExpert accept a simpler structure too:
        raw = ref.propose_two_stage(merged, cycle_nodes=ctx.nodes)
        return extract_refactoring_prompt(raw)
