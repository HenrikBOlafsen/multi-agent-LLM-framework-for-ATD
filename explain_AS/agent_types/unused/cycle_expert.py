from agent_setup import AgentBase
from typing import Dict, Tuple


CYCLE_EXPERT_SYSTEM = """You are a Cycle_Expert for a dependency cycle.
Your job is rewrite/reformat the given data. This data will later be used by another agent to propose a SMALL, ARCHITECTURAL change that breaks the static cycle without changing behavior or public API.

House policy (ATD):
- ANY module reference counts (dynamic/lazy/type-only all count).
- We care about architecture (static coupling), not runtime import order.

You should look at all the info you were given and rewrite it to only include relevant info. So anything that is not relevant to the static coupling should be dropped, as to not confuse the next agent with unecessary info. Shorten any code to only include useful info, and make abstractions (to explain the code) where suitable.

If you are unsure about whether some info should be dropped or included, include it. But don't be afraid to drop info that does not seem useful to the agent that is to decide how to break the cycle to remove the static coupling.

Style:
- Imperative, specific to the given files and edges.
"""


class CycleExpert(AgentBase):
    def __init__(self, name: str, client):
        super().__init__(name, client, CYCLE_EXPERT_SYSTEM)

    def propose(self, dep_summaries_A: Dict[str, Tuple[str, str]], dep_summaries_B: Dict[str, Tuple[str, str]]) -> str:
        """
        dep_summaries: list of (A_path, B_path, dep_expert_text)
        """
        self.reset()
        A_deps_text = "\n\n".join(
            [f"Edge {i+1}: {a} → {b}\n{txt}"
            for i, (a, (b, txt)) in enumerate(dep_summaries_A.items())]
        )
        B_deps_text = "\n\n".join(
            [f"Edge {i+1}: {a} → {b}\n{txt}"
            for i, (a, (b, txt)) in enumerate(dep_summaries_B.items())]
        )

        user = f"""Here is the data:

Context (for each edge where A depends on B (A->B) here are summaries of how A depends on B, made by other agents):
{A_deps_text}

More context (summaries of what parts of B that A depends on, for each edge A->B, made by agents):
{B_deps_text}

Keep it friendly, specific to these files and human oriented. Do not mention parts of the code that is not relevant to our minimal refactoring, as to not confuse the reader of your generated prompt.
"""
        return self.ask(user)