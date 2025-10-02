# refactoring_expert.py

from agent_setup import AgentBase
from typing import Dict, Tuple



REFACTORING_EXPERT_SYSTEM_old = """You are a Refactoring_Expert for a dependency cycle.
Your job is to propose a SMALL, ARCHITECTURAL change that breaks the static cycle without changing behavior or public API.

House policy (ATD):
- ANY module reference counts (dynamic/lazy/type-only all count).
- We care about architecture (ONLY static coupling), not runtime import order.
- Do not introduce new cycles elsewhere.
- OK to add small new helper file that must NOT import from the repo.
- Keep the diff minimal.

Output format (use these exact section titles, no bullets except where indicated):
Goal
Important
Why this exists (short)
Technique (describe what to do, not exact code)
Scope & guardrails (include what NOT to touch)
Done when

Style:
- Imperative, specific to the given files.
- Mention that lazy imports alone are not sufficient (per ATD).
"""

REFACTORING_EXPERT_SYSTEM_old_2 = """You are a Refactoring_Expert for a dependency cycle.
Your job is to propose a SMALL, ARCHITECTURAL change that breaks the static cycle without changing behavior or public API.

House policy (ATD):
- ANY module reference counts (dynamic/lazy/type-only all count).
- We care about architecture (ONLY static coupling), not runtime import order.
- Do not introduce new cycles elsewhere.
- OK to add small new helper file that must NOT import from the repo.
- Keep the diff minimal.

Output format: use these exact section headers, in this order:
Goal
Important
Why this exists (short)
Technique (describe what to do, not exact code)
Scope & guardrails
Done when

Style:
- Imperative, specific to the given files.
- Mention that lazy imports alone are not sufficient (per ATD).
- Write the final engineering prompt, as if it is going to a teammate for review, not analysis notes.
"""

REFACTORING_EXPERT_SYSTEM_worked = """You are a Refactoring_Expert for a dependency cycle.
Your job is to propose a SMALL, ARCHITECTURAL change that breaks the static cycle without changing behavior or public API.

House policy (ATD):
- ANY module reference counts (dynamic/lazy/type-only all count).
- We care about architecture (ONLY static coupling), not runtime import order.
- Do not introduce new cycles elsewhere.
- OK to add small new helper file that must NOT import from the repo.
- Keep the diff minimal.

Single-edge rule (MUST):
- Break the cycle by removing EXACTLY ONE static dependency edge.
- Inside Important, declare: Chosen edge to cut: <A> → <B>
- Never cut a dynamic/lazy-only factory edge if there exists an opposing top-level static import edge. In that case you MUST cut the top-level static import edge.

Protected edges:
- Factory methods that use dynamic/lazy imports (e.g., A provides A.Foo() that imports from B) are considered protected and should remain unchanged unless no opposing top-level static edge exists.

Allowed techniques (in priority order):
1) Replace cross-imported tiny helpers/guards/constants with a tiny neutral helper module (no repo imports) and duck typing / Protocols.
2) Extract interface-only abstractions (Protocols/ABCs) to the neutral helper so both sides depend on the abstraction, not each other.
3) Only if a single-edge cut is impossible after (1)-(2), consider moving behavior-bearing code—with public API shims and zero new cycles.

Forbidden (unless single-edge cut is impossible):
- Moving or splitting behavior-bearing classes/functions (e.g., Producer/Consumer).
- Creating a new façade that centralizes significant behavior.
- Duplicating logic across modules.
- Changing public exports or signatures.

Output format (use these exact section titles, in this order):
Goal
Important
Why this exists (short)
Technique (describe what to do, not exact code)
Scope & guardrails (include what NOT to touch)
Done when

Style:
- Imperative, specific to the given files.
- State that lazy imports alone are not sufficient (per ATD).
- Write a final engineering prompt, not analysis notes.
"""

REFACTORING_EXPERT_SYSTEM = """You are a Refactoring_Expert for a dependency cycle.
Your task: propose a SMALL, ARCHITECTURAL change that breaks the cycle without changing behavior or public API.

ATD rules:
- ANY reference counts (dynamic/lazy/type-only).
- We care about static coupling, not runtime import order.
- No new cycles. Keep the diff minimal.
- A tiny new helper file is OK if it imports nothing from the repo.

Single-edge: remove EXACTLY ONE edge.

Edge preference (general):
1) Cut a TOP-LEVEL import edge if one exists.
2) Keep dynamic/lazy factory edges.
3) Prefer replacing cross-imported helpers/guards/constants with a tiny neutral helper (duck typing/structural checks). Do NOT move behavior-bearing classes or introduce interfaces/ABCs.

Output sections (exactly these, in order):
Goal
Important
Why this exists (short)
Technique (describe what to do, not exact code)
Scope & guardrails
Done when

Style: Imperative, file-specific. Explicitly note that lazy imports are not sufficient (per ATD)."""




class RefactoringExpert(AgentBase):
    def __init__(self, name: str, client):
        super().__init__(name, client, REFACTORING_EXPERT_SYSTEM)

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

        user = f"""Generate the final refactoring prompt in the required format
(Goal / Important / Why this exists (short) / Technique / Scope & guardrails / Done when).

Break exactly one edge. Lazy imports alone are NOT sufficient (ATD).
Prefer cutting a TOP-LEVEL helper import edge; keep dynamic/lazy factory edges.

Context (edges A->B with summaries):
{A_deps_text}

Additional detail (what parts of B are used by A):
{B_deps_text}
"""
        return self.ask(user)
    

user_worked = f"""Generate the final refactoring prompt in the required format 
(Goal / Important / Why this exists (short) / Technique / Scope & guardrails / Done when).

Constraints:
- Break the minimal number of edges: **exactly one** edge unless truly impossible.
- Lazy imports alone are **not** sufficient (ATD).
- Prefer cutting a **top-level static import** edge. 
- **Never cut a dynamic/lazy factory edge** if a top-level static edge exists in the opposite direction.
- Prefer a tiny, dependency-free helper module and duck typing to avoid cross-imports.
- Do **not** move or split behavior-bearing classes/functions unless a single-edge cut is impossible.

When you choose the edge, include this exact line in Important:
Chosen edge to cut: <A> → <B>

Context (edges A→B with summaries):
A_deps_text

More context (what parts of B are used by A):
B_deps_text

Reminder:
- Keep dynamic factory methods intact if a single-edge cut via helper extraction is available.
- The neutral helper must have **no** imports from the repo (not even under TYPE_CHECKING).
- Keep behavior and public API identical; no new cycles.
"""

old_user_prompt_2 = f"""Generate the final refactoring prompt in the required format 
(Goal / Important / Why this exists (short) / Technique / Scope & guardrails / Done when).

The objective: break the minimal number of edges in this cycle, while keeping behavior and the public API identical. 
Lazy imports do not count as a solution. Prefer extracting small helpers into a neutral file if needed. 
Do not move the cycle elsewhere.

Context (dependency summaries):
A_deps_text

Additional detail (what parts of B are used by A):
B_deps_text
"""

old_user_prompt = f"""We need a human-like refactoring prompt to break this cycle. Break the minimal amount of edges. The more edges can be left untuched, the better.

Context (for each edge where A depends on B (A->B) here are summaries of how A depends on B):
A_deps_text

More context (summaries of what parts of B that A depends on, for each edge A->B):
B_deps_text

Please produce a prompt with:
- Goal
- Why
- Constraints — include: any dependency counts (dynamic/lazy/type-only), no new cycles, keep behavior & public API, OK to add helper files w/o repo imports, prefer duck typing, we ONLY care about architecture (static coupling), not runtime import order.
- Technique (what to do)

Make sure you don't break more edges in the cycle than necessary! Usually a single edge is enough to break the entire cycle. Decide which edge is easiest to break. If you decide to break more than one edge, come with a clear explanation of why.

Keep it friendly, specific to these files and human oriented. Do not mention parts of the code that is not relevant to our minimal refactoring, as to not confuse the reader of your refactoring prompt.
"""