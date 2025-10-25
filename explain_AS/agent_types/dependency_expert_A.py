from agent_setup import AgentBase
from agent_util import clip

DEPENDENCY_EXPERT_A_SYSTEM = """You are a Dependency_Expert for a single edge A->B in a cycle.
Your job:
Explain precisely where and how A depends on B.
Quote relevant code (with line numbers) and explain, but do not include all code, only relevant code for the dependency A->B. And shorten code by making abstractions of it, like e.g. summarizing it in plain text.
Describe the edge: top-level import, dynamic import, re-export, type-only, test-only etc. (these are just some suggestions). Also describe if it is e.g. inside a function or class etc.
My ATD metric treats ANY module reference as a dependency (dynamic/lazy all count). I care about architecture (static coupling), not just runtime import order.

And also explain how the stuff that was imported from B is used by A. For each thing imported from B, explain the context of how and where it is used. 
In your output, name the files by their actual name, not "A" and "B".
Make sure to not miss any important info that could be relevant later when assesing whether to break this edge (You are not to make this assessment. You just gather info).

Rules:
- Stay factual. if unsure, say so.
- Your output should be human-readable and well explained, not JSON or tables, but natural language.
"""

class DependencyExpertA(AgentBase):
    def __init__(self, name: str, client):
        super().__init__(name, client, DEPENDENCY_EXPERT_A_SYSTEM)
    
    def summarize_dependency(self, file_path_A: str, file_path_B: str, file_A_text: str) -> str:
        self.reset()
        user = f"""File A: {file_path_A}. File B {file_path_B}.

Please summarize how file A depends on file B, for later use by other agents. Only caring about static coupling. Name the files by their actual names (don't call them A and B).

Here is file A:

=== BEGIN FILE ===
{clip(file_A_text)}
=== END FILE ===

"""
        return clip(self.ask(user))
