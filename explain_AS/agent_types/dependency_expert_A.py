# dependency_expert_A.py

from agent_setup import AgentBase
from agent_util import clip

DEPENDENCY_EXPERT_A_SYSTEM_best = """You are a Dependency_Expert for a single edge A->B in a cycle.
Your job:
Explain precisely where A depends on B (import site, call, re-export).
Quote relevant code (with line numbers) and explain what crosses the edge.
Classify the edge: top-level import, dynamic import, re-export, type-only, test-only, reflection/DI, or build-only.
My ATD metric treats ANY module reference as a dependency (dynamic/lazy/type-only all count). I care about architecture (static coupling), not runtime import order.
Include flags: Top-level import: yes/no · Inside function: yes/no.
Rules:
- Stay factual. if unsure, say so.
- Your output should be human-readable and well explained, not JSON.
"""

DEPENDENCY_EXPERT_A_SYSTEM = """You are a Dependency_Expert for a single edge A->B in a cycle.
Your job:
Explain precisely where A depends on B (import site, call, re-export).
Quote relevant code (with line numbers) and explain what crosses the edge.
Classify the edge: top-level import, dynamic import, re-export, type-only, test-only, reflection/DI, or build-only. Include flags: Inside function: yes/no.
My ATD metric treats ANY module reference as a dependency (dynamic/lazy/type-only all count). I care about architecture (static coupling), not runtime import order.

Rules:
- Stay factual. if unsure, say so.
- Your output should be human-readable and well explained, not JSON.
"""


DEPENDENCY_EXPERT_A_SYSTEM_test = """You are a Dependency_Expert for a single edge ModuleA -> ModuleB in a cycle.
Report neutrally and repo-agnostically:

1) EXACT edge symbols (copyable list): for each symbol that ModuleA references from ModuleB at module scope, list name + where used (with line numbers). Include type-only and re-exports if present.
2) Import sites: top-level vs inside function; dynamic imports; re-exports.
3) Cross-module nominal checks in ModuleA that reference ModuleB (e.g., isinstance/issubclass), with line numbers.
4) Classify each referenced symbol by weight: TINY_HELPER / FACTORY_FN / DATA_CLASS / HEAVY_CLASS.
5) Public API exposure: does ModuleA re-export anything from ModuleB? do callers import through ModuleA?
6) Edge strength flags: Top-level: yes/no · Type-only: yes/no · Dynamic: yes/no · Test-only: yes/no.

My ATD metric treats ANY module reference as a dependency (dynamic/lazy/type-only all count). I care about architecture (static coupling), not runtime import order.

Rules: stay factual; quote only small, relevant snippets with line numbers; human-readable, not JSON."""



class DependencyExpertA(AgentBase):
    def __init__(self, name: str, client):
        super().__init__(name, client, DEPENDENCY_EXPERT_A_SYSTEM)
    
    def summarize_dependency(self, file_path_A: str, file_path_B: str, file_A_text: str) -> str:
        self.reset()
        user = f"""File A: {file_path_A}. File B {file_path_B}.

Please summarize how file A depends on file B, for later use by other agents. Only caring about static coupling.

Here is file A:

=== BEGIN FILE ===
{clip(file_A_text)}
=== END FILE ===

"""
        return self.ask(user)

    def answer_question(self, file_path: str, file_text: str, question: str) -> str:
        # For follow-ups, include the file again (24B context). Keep it light; model should quote minimally.
        self.reset()
        user = f"""File: {file_path}

Question: {question}

=== BEGIN FILE ===
{clip(file_text)}
=== END FILE ===
"""
        return self.ask(user)