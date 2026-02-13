from __future__ import annotations

from typing import Dict, Tuple

from agent_setup import log_section, log_line, Ansi
from agent_types.dependency_expert_A import DependencyExpertA
from agent_types.dependency_expert_B import DependencyExpertB
from agent_types.cycle_expert import CycleExpert
from agent_types.refactoring_expert import RefactoringExpert

from .base import OrchestratorBase, CycleContext, node_to_abs, extract_refactoring_prompt


class OrchestratorV1FourAgents(OrchestratorBase):
    def run(self, ctx: CycleContext, *, refactor_prompt_variant: str) -> str:
        log_section("OrchestratorV1FourAgents", "cyan")
        files = ctx.read_cycle_files()

        # Dependency expert A (A -> B)
        log_section("Dependency Expert A (A->B)", "magenta")
        depA = DependencyExpertA("Dependency_Expert_A", self.client)
        dep_summ_A: Dict[str, Tuple[str, str]] = {}  # a_path -> (b_path, summary)
        for i, e in enumerate(ctx.edges, 1):
            a_node, b_node = str(e["source"]), str(e["target"])
            a_path = node_to_abs(ctx.repo_root, a_node)
            b_path = node_to_abs(ctx.repo_root, b_node)
            log_line(f"[A:{i}] {a_node} -> {b_node}", Ansi.MAGENTA)
            dep_summ_A[a_path] = (b_path, depA.summarize_dependency(a_path, b_path, files[a_path]))

        # Dependency expert B (parts of B used by A)
        log_section("Dependency Expert B (parts of B used by A)", "yellow")
        depB = DependencyExpertB("Dependency_Expert_B", self.client)
        dep_summ_B: Dict[str, Tuple[str, str]] = {}  # a_path -> (b_path, summary)
        for i, e in enumerate(ctx.edges, 1):
            a_node, b_node = str(e["source"]), str(e["target"])
            a_path = node_to_abs(ctx.repo_root, a_node)
            b_path = node_to_abs(ctx.repo_root, b_node)
            log_line(f"[B:{i}] {a_node} -> {b_node}", Ansi.YELLOW)
            prev_a = dep_summ_A.get(a_path, ("", ""))[1]
            dep_summ_B[a_path] = (b_path, depB.summarize_dependency(a_path, b_path, files[b_path], prev_a))

        # Cycle expert
        log_section("Cycle Expert (explain cycle)", "green")
        cyc = CycleExpert("Cycle_Expert", self.client)
        cycle_explanation = cyc.explain(dep_summ_A, dep_summ_B)

        # Refactoring expert (final prompt)
        log_section("Refactoring Expert (final prompt)", "green")
        ref = RefactoringExpert("Refactoring_Expert", self.client, prompt_variant=refactor_prompt_variant)
        raw = ref.propose(dep_summ_A, dep_summ_B, cycle_explanation)
        return extract_refactoring_prompt(raw)
