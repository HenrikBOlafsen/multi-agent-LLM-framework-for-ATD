from agent_setup import AgentBase
from typing import Dict, Tuple


CYCLE_EXPERT_SYSTEM = """You are a Cycle_Expert for a dependency cycle.
Your job is to explain a dependency cycle. This explanation will later be used by another agent to propose a small, architectural change that breaks the static cycle without changing behavior or public API.

House policy (ATD):
- ANY reference counts (dynamic/lazy). Making imports lazy or dynamic is NOT sufficient as they are still static coupling.
- Ignore type-only references (anything under TYPE_CHECKING).
- We care about architecture (static coupling), not runtime import order.

Include exactly the sections:
General explanation
Impact

Style:
- Imperative, specific to the given files and edges. Try to keep it short, but not too short so that important context is lost.
"""


class CycleExpert(AgentBase):
    def __init__(self, name: str, client):
        super().__init__(name, client, CYCLE_EXPERT_SYSTEM)

    def explain(self, dep_summaries_A: Dict[str, Tuple[str, str]], dep_summaries_B: Dict[str, Tuple[str, str]]) -> str:
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

Keep it friendly, specific to these files and human oriented.
"""
        return self.ask(user)