import os
from typing import Dict, List, Tuple
from agent_setup import LLMClient, log_section, log_line, Ansi
from agent_types.dependency_expert_A import DependencyExpertA
from agent_types.dependency_expert_B import DependencyExpertB
from agent_types.refactoring_expert import RefactoringExpert
from agent_types.cycle_expert import CycleExpert
from agent_util import default_node_to_path, read_file
import re
from explain_cycle_minimal import TEMPLATE as BASE_TEMPLATE, cycle_chain_str


# -------------------------
# Orchestrator
# -------------------------

class Orchestrator:
    def __init__(self, client: LLMClient, package_root: str):
        self.client = client
        self.package_root = package_root

    @staticmethod
    def _extract_refactoring_prompt(text: str) -> str:
        m = re.search(r"<<<BEGIN_REFACTORING_PROMPT>>>(.*?)<<<END_REFACTORING_PROMPT>>>", text, re.DOTALL)
        return m.group(1).strip() if m else text.strip()

    def run(self, repo_root: str, cycle: Dict) -> str:
        """Run the full pipeline on one cycle dict."""
        log_section("Pipeline start")
        nodes: List[str] = cycle["nodes"]
        edges: List[Dict] = cycle["edges"]
        log_line(f"Cycle ID: {cycle.get('id', '<no id>')} | length={cycle.get('length', len(nodes))}", Ansi.GRAY)
        log_line(f"Nodes: {nodes}", Ansi.GRAY)
        log_line(f"Edges: {[ (e['source'], '->', e['target']) for e in edges ]}", Ansi.GRAY)

        # Resolve file paths and read files
        log_section("Resolve & read files", "cyan")
        files: Dict[str, str] = {}
        for node in nodes:
            path = default_node_to_path(repo_root, self.package_root, node)
            if not os.path.exists(path):
                raise FileNotFoundError(f"Path not found for node '{node}': {path}")
            files[path] = read_file(path)
            log_line(f"OK: {path}", Ansi.DIM)

        # 1) Dependency_Experts A
        log_section("Dependency Expert A (A->B)", "magenta")
        dep_expert_A = DependencyExpertA("Dependency_Expert_A", self.client)
        dependency_summaries_A: Dict[str, Tuple[str, str]] = {} # key: a_path, content: (b_path, summary_a)
        for i, e in enumerate(edges, 1):
            a_node, b_node = e["source"], e["target"]
            a_path = default_node_to_path(repo_root, self.package_root, a_node)
            b_path = default_node_to_path(repo_root, self.package_root, b_node)
            log_line(f"[A:{i}] {a_node} -> {b_node}", Ansi.MAGENTA)
            a_file = files[a_path]
            dependency_summaries_A[a_path] = (b_path, dep_expert_A.summarize_dependency(a_path, b_path, a_file))

        # 2) Dependency_Experts B
        log_section("Dependency Expert B (parts of B used by A)", "yellow")
        dep_expert_B = DependencyExpertB("Dependency_Expert_B", self.client)
        dependency_summaries_B: Dict[str, Tuple[str, str]] = {} # key: a_path, content: (b_path, summary_b)
        for i, e in enumerate(edges, 1):
            a_node, b_node = e["source"], e["target"]
            a_path = default_node_to_path(repo_root, self.package_root, a_node)
            b_path = default_node_to_path(repo_root, self.package_root, b_node)
            log_line(f"[B:{i}] {a_node} -> {b_node}", Ansi.YELLOW)
            dep_summary_b = dep_expert_B.summarize_dependency(
                a_path, b_path, files[b_path], dependency_summaries_A[a_path][1],
            )
            dependency_summaries_B[a_path] = (b_path, dep_summary_b)

        # 3) Cycle_Expert -> final prompt
        log_section("Cycle Expert (explain cycle)", "green")
        cycle_expert = CycleExpert("Cycle_Expert", self.client)
        cycle_explanation = cycle_expert.explain(dependency_summaries_A, dependency_summaries_B)

        # 4) Refactoring_Expert -> final prompt
        log_section("Refactoring Expert (propose refactoring prompt)", "green")
        refactoring_expert = RefactoringExpert("Refactoring_Expert", self.client)
        raw = refactoring_expert.propose(
            dependency_summaries_A,
            dependency_summaries_B,
            cycle_explanation
        )
        final_prompt = self._extract_refactoring_prompt(raw)

        # Build the minimal base template and append the two generated sections
        size = cycle.get("length", len(nodes))
        chain = cycle_chain_str(nodes)
        base = BASE_TEMPLATE.format(size=size, chain=chain)

        combined = f"{base}\n\n{final_prompt}"
        return combined


# -------------------------
# CLI / Example usage
# -------------------------

if __name__ == "__main__":
    import argparse
    import json
    import os
    from pathlib import Path
    from typing import Dict

    # Defaults (can still be overridden via args or env)
    DEFAULT_LLM_URL = os.environ.get("LLM_URL", "http://host.docker.internal:8012/v1/chat/completions")
    DEFAULT_API_KEY = os.environ.get("API_KEY", "token")
    DEFAULT_MODEL = os.environ.get("MODEL", "Qwen/Qwen3-Coder-30B-A3B-Instruct")

    parser = argparse.ArgumentParser(description="Explain a dependency cycle and propose a refactoring prompt.")
    parser.add_argument("--repo-root", type=str, help="Absolute or relative path to the repository root.")
    parser.add_argument("--src-root", type=str, help="Package root relative to repo (e.g., 'kombu' or 'src/werkzeug').")
    parser.add_argument("--cycle-json", type=str, help="Path to module_cycles.json output from analyze_cycles.sh.")
    parser.add_argument("--cycle-id", type=str, help="ID of the representative cycle to explain (e.g., 'scc_0_cycle_0').")
    parser.add_argument("--out-prompt", type=str, default=None, help="If set, write the final refactoring prompt to this file.")
    parser.add_argument("--llm-url", type=str, default=DEFAULT_LLM_URL, help="LLM API URL (overrides env LLM_URL).")
    parser.add_argument("--api-key", type=str, default=DEFAULT_API_KEY, help="LLM API key (overrides env API_KEY).")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model name or id (overrides env MODEL).")

    args = parser.parse_args()

    def load_cycle_from_json(json_path: str, cycle_id: str) -> Dict:
        data = json.loads(Path(json_path).read_text())
        for scc in data.get("sccs", []):
            for cyc in scc.get("representative_cycles", []):
                if cyc.get("id") == cycle_id:
                    return cyc
        raise KeyError(f"Cycle id '{cycle_id}' not found in {json_path}")

    # If CLI args provided, run in non-interactive mode
    if args.repo_root and args.src_root and args.cycle_json and args.cycle_id:
        LLM_URL = args.llm_url
        API_KEY = args.api_key
        MODEL = args.model

        # Assumes LLMClient, Orchestrator, log_section, log_line, Ansi exist above
        client = LLMClient(LLM_URL, API_KEY, MODEL, temperature=0.1, max_tokens=16384)
        orch = Orchestrator(client, package_root=args.src_root)

        try:
            cycle = load_cycle_from_json(args.cycle_json, args.cycle_id)
            prompt = orch.run(args.repo_root, cycle)
            log_section("FINAL REFACTORING PROMPT", "green")
            print(prompt)
            if args.out_prompt:
                Path(args.out_prompt).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out_prompt).write_text(prompt)
                log_line(f"Wrote final prompt to: {args.out_prompt}", Ansi.GREEN)
            log_section("END", "green")
        except Exception as e:
            log_section("Pipeline error", "red")
            print(e)
            raise SystemExit(1)
    else:
        # Optional fallback demo (safe to keep/remove)
        LLM_URL = DEFAULT_LLM_URL
        API_KEY = DEFAULT_API_KEY
        MODEL = DEFAULT_MODEL

        REPO_ROOT = "projects_to_analyze/kombu"
        cycle_kombu = {
            "id": "scc_demo",
            "length": 2,
            "nodes": ["connection.py", "messaging.py"],
            "edges": [
                {"source": "connection.py", "target": "messaging.py", "relation": "module_dep"},
                {"source": "messaging.py", "target": "connection.py", "relation": "module_dep"},
            ],
            "summary": "Representative cycle of length 2",
        }

        client = LLMClient(LLM_URL, API_KEY, MODEL, temperature=0.1, max_tokens=16384)
        orch = Orchestrator(client, package_root="kombu")

        try:
            prompt = orch.run(REPO_ROOT, cycle_kombu)
            log_section("FINAL REFACTORING PROMPT", "green")
            print(prompt)
            log_section("END", "green")
        except Exception as e:
            log_section("Pipeline error", "red")
            print(e)
            raise SystemExit(1)
