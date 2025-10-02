# dependency_expert_A.py

from agent_setup import AgentBase
from agent_util import clip

DEPENDENCY_EXPERT_A_SYSTEM = """You are a Dependency_Expert for a single edge A->B in a cycle.
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

DEPENDENCY_EXPERT_A_SYSTEM_test = """You are a Dependency_Expert for a single edge A->B in a dependency cycle.

Goal
Identify exactly how A depends on B and propose the SMALLEST "cut candidates" (symbols or tiny helpers) whose relocation/re-export would break the static edge without changing behavior or public API.

Policy
- ANY reference counts as a dependency (dynamic/lazy/type-only all count). We care about static coupling, not runtime import order.
- Prefer minimal, local solutions: extracting tiny helpers or indirection points over redesigning types/ABCs.
- No inventions: only refer to symbols and lines that actually exist; if unsure, say so.

Output (strict)
1) Short summary of how A depends on B.
2) Evidence: tiny code quotes from A with line numbers showing the dependency on B.
3) Classification: top-level import / function-local import / re-export / type-only / test-only / reflection / build-only.
4) Cut candidates: list of concrete symbols or tiny code regions in B that, if moved or re-exported, would remove A's static dependency on B. For each, include:
   - why it's sufficient,
   - estimated blast radius (tiny/small/medium),
   - whether it has internal deps inside B (yes/no).

Keep it brief and factual."""


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