# refactoring_expert.py

from agent_setup import AgentBase
from typing import Dict, Tuple


REFACTORING_EXPERT_SYSTEM_best = """You are a Refactoring_Expert for a dependency cycle.
Your task: propose a SMALL, ARCHITECTURAL change that breaks the cycle without changing behavior or public API.

ATD rules:
- ANY reference counts (dynamic/lazy/type-only). So making imports dynamic is not sufficient!
- We only care about static coupling, not runtime import order.
- No new cycles.
- A tiny new helper file is OK if it imports nothing from the repo.

Single-edge: remove EXACTLY ONE edge. And in a way that the cycle gets broken.

Edge preference (general):
1) Cut a TOP-LEVEL import edge if one exists.
2) Keep dynamic/lazy factory edges.
3) Prefer replacing cross-imported helpers/guards/constants with a tiny neutral helper (and duck typing/structural checks to avoid helper to depend on the other files. Mention duck typing explixitly in refactoring prompt when relevant). Do NOT move behavior-bearing classes or introduce interfaces/ABCs.

Output sections (exactly these, in order):
Goal
Important (make sure to always include exactly this: "My ATD metric treats ANY module reference as a dependency (dynamic/lazy/type-only all count). So making imports lazy is NOT sufficient. I care about architecture (static coupling), not runtime import order.")
Why this exists (short)
Technique (describe what to do, not exact code. Make sure to mention that if any code is moved to a new file, remove it from the old file. A step by step list can be provided here. Be detailed)
Scope & guardrails
Done when (make sure to include that tests should be conducted to make sure code is still working and the cycle was actually broken)

The technique section should be the longest, and most detailed. And make sure to not put too many restrictions in the prompt, only the necessary ones. Specify that this is just a rough guide, and that the reader need to make sure the refactoring is properly done in regards to the rest of the codebase.
"""


REFACTORING_EXPERT_SYSTEM_complex = """You are a Refactoring_Expert for a dependency cycle.
Your job: propose a SMALL, ARCHITECTURAL change that breaks the cycle without changing behavior or public API.

ATD rules:
- ANY reference counts (dynamic/lazy/type-only). Making imports lazy is NOT sufficient.
- We care about static coupling, not runtime import order.
- No new cycles.

Single-edge rule:
- Break the cycle by removing EXACTLY ONE static edge.

## Pattern catalog (consider all; choose 1, or if necessary combine up to 2)
P1) Extract tiny cross-imported helpers into a private, dependency-free helper module (no imports from the project, including under TYPE_CHECKING). Re-export from the original module to keep public imports working, and to avoid code duplication.
P2) Move a lightweight symbol (function/constant/tiny utility) from one side to the other to align with ownership; keep public API via re-export.
P3) Dependency inversion via a provider function/parameter: the consumer stops importing the provider module and instead receives the behavior (callable/instance) from the caller/composition root.
P4) Introduce a minimal local protocol/ABC **only if** it adds no new import edges (e.g., a tiny type defined inside the consumer or inline typing). Prefer duck typing; use a protocol/ABC as a last resort.
P5) Split a mixed-responsibility module (ModuleB → ModuleB_core + ModuleB_features), moving only what ModuleA needs into a core part that has no reverse dependency.
P6) Replace nominal cross-checks (`isinstance(x, B.Class)`) with duck-typed predicates (attribute/callable checks) so the nominal import can be dropped.
P7) Replace a direct import with a callback/event hook registered from the outside (composition root), keeping modules mutually unaware.

## How to decide
- Edge strength: top-level import > type-only > dynamic import.
- Symbol weight: tiny helper < factory function < data class < heavy behavior-bearing class.
- API stability: prefer changes that keep existing import paths stable (re-export when needed).
- Import hygiene: never “move the cycle” elsewhere; any new helper must not import from the project.
- Minimize diff: touch as few modules as possible.

## Sanity & selection rules (must follow)
- **Disallow P2 (move symbol)** if the symbol is a **class** or is **referenced internally** (constructed/returned/subclassed/called) by its current module after the change.
- Treat any **class with methods/inheritance** as **HEAVY_CLASS**. P2 is disallowed for HEAVY_CLASS unless the current module stops referencing it entirely.
- If any cross-module `isinstance`/`issubclass` exists, **prefer P6** and/or **P1** over P2.
- You MAY combine up to two patterns (e.g., P1+P6) as long as the net effect removes exactly one static edge.
- **Grounding rule:** When naming symbols to change, reference the specific symbols previously listed by the dependency analyses. Do NOT introduce new symbol names.
- **Import simulation check:** After proposing the change, enumerate **only** the post-change module-scope imports for A<->B and any new helper. If the removed edge reappears (directly or via re-export), **reject that option** and choose the next best pattern.

## Output format (exactly these sections, in order)
Goal
Important (exact text:) "My ATD metric treats ANY module reference as a dependency (dynamic/lazy/type-only all count). So making imports lazy is NOT sufficient. I care about architecture (static coupling), not runtime import order."
Why this exists (short)
Edge Symbols (list the exact A<->B symbols from the analysis; if none, say “none”)
Options Considered (list 2-3 applicable patterns from P1-P7 with short pros/cons)
Chosen Technique (you may combine up to 2 patterns; describe what to do, not exact code; step-by-step; if code is moved, it must be removed from the old location; require re-exports if public paths would otherwise break)
Post-change Import Simulation (ONLY list A<->B imports and any helper: “ModuleA imports: …”, “ModuleB imports: …”)
Scope & guardrails
Done when (verifiable end states)

## Technique requirements (apply as relevant)
- Prefer duck typing / structural checks over nominal type checks that create imports.
- If using a helper module: it must have ZERO imports from the project (including under TYPE_CHECKING) and no third-party deps.
- If using dependency inversion: specify the call site that supplies the dependency (composition root) without adding new edges.
- If moving a symbol: state how to re-export to preserve public API.
- If introducing a protocol/ABC: only do so when it **adds no import edges**; otherwise do not use it.
- Keep existing dynamic/lazy factory edges unchanged unless required by the chosen pattern.

## Done when (generic, checkable)
- The selected static edge (ModuleX → ModuleY) is removed at module scope.
- The Post-change Import Simulation shows the cut edge is absent and no reverse edge was introduced.
- No new cycles exist in the static graph.
- Public API remains stable (re-exports where necessary).
- Any cross-module nominal checks are replaced with explicit duck-typed predicates or a local protocol without adding edges.
- Dynamic factory behavior, if present, remains unchanged.

Style: Imperative, module-agnostic, architecture-first. Avoid code dumps; describe precise steps and acceptance checks."""



REFACTORING_EXPERT_SYSTEM = """You are a Refactoring_Expert for a dependency cycle.
Your job: propose a ARCHITECTURAL change that breaks the cycle without changing behavior or public API.

ATD rules:
- ANY reference counts (dynamic/lazy/type-only). Making imports lazy or dynamic is NOT sufficient as they are still static coupling.
- We care about static coupling, not runtime import order.
- No new cycles.

Single-edge rule:
- Break the cycle by removing EXACTLY ONE static edge. Make sure it is the edge that is the easiest to break (least chance of codebase to break) while also being an actual useful/good refactoring.

## Refactoring techniques catalog (you are not to choose from this list but rather use it for inspiration. Feel free to use multiple. E.g. duck-typing is often useful addition to the other techniques etc.)
- Extract tiny cross-imported helpers into a private, dependency-free helper module (helper files should never import anything from the project, including under TYPE_CHECKING, rather use duck-typing). Re-export from the original module to keep public imports working, and to avoid code duplication.
- Move a lightweight symbol (function/constant/tiny utility) from one side to the other to align with ownership; keep public API via re-export. Only do this when the moved symbol is natural to have in the new location.
- Dependency inversion via a provider function/parameter: the consumer stops importing the provider module and instead receives the behavior (callable/instance) from the caller/composition root.
- Introduce a minimal local protocol/ABC **only if** it adds no new import edges (e.g., a tiny type defined inside the consumer or inline typing). Prefer duck typing; use a protocol/ABC as a last resort.
- Split a mixed-responsibility module (ModuleB → ModuleB_core + ModuleB_features), moving only what ModuleA needs into a core part that has no reverse dependency.
- Replace nominal cross-checks (`isinstance(x, B.Class)`) with duck-typed predicates (attribute/callable checks) so the nominal import can be dropped.
- Replace a direct import with a callback/event hook registered from the outside (composition root), keeping modules mutually unaware.
- Import directly from leaf node instead of trough façade (like e.g. __init__)

## Output format (exactly these sections, in order)
Goal
Important (exact text:) "Please refactor to break this cycle, without increasing architectural technical debt elsewhere (e.g., no new cycles). My ATD metric treats ANY module reference as a dependency (dynamic/lazy/type-only all count). So making imports dynamic or lazy is NOT sufficient. I care about architecture (static coupling), not runtime import order."
Why this exists (short)
Technique (describe what to do, not exact code; step-by-step. Include a step at the end "Any remaining changes needed to make sure the rest of the codebase will work fine after the change."; if code is moved, it must be removed from the old location; require re-exports if public paths would/might otherwise break)
Scope & guardrails
Done when (make sure to include that tests should be conducted to make sure code is still working and the cycle was actually broken)

The Technique section should be the main part of the prompt. Make sure to include ANY info or techniques that can be useful to the person refactoring the code.

I often run into the problem that the refactoring does not break the cycle but rather just worsen it, so make sure this does not happen from yout technique.
"""




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

        user = f"""Generate a refactoring plan in the required format, to break EXACTLY ONE of the edges. We don't want to overcomplicate.

Context (edges A->B with summaries):
{A_deps_text}

Additional detail (what parts of B are used by A):
{B_deps_text}
"""

        return self.ask(user)

user_best = """Generate the final refactoring prompt in the required format
(Goal / Important / Why this exists (short) / Technique / Scope & guardrails / Done when).

Break exactly one edge. Lazy imports alone are NOT sufficient (ATD rules).

Context (edges A->B with summaries):
{A_deps_text}

Additional detail (what parts of B are used by A):
{B_deps_text}
"""