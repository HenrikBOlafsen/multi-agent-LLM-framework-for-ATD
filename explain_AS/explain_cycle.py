# explain_cycle.py
# Small-model multi-agent pipeline to generate a refactoring prompt that breaks a module cycle.
# - Language neutral: feeds raw file text; no AST
# - Human-readable IO only (no JSON)
# - Talks to LM Studio-compatible /v1/chat/completions endpoint

import os
from typing import Dict, List, Tuple
from agent_setup import LLMClient, log_section, log_line, Ansi
from agent_types.dependency_expert_A import DependencyExpertA
from agent_types.dependency_expert_B import DependencyExpertB
from agent_types.cycle_expert import CycleExpert
from agent_types.refactoring_expert import RefactoringExpert
from agent_util import default_node_to_path, read_file

# -------------------------
# Orchestrator
# -------------------------

class Orchestrator:
    def __init__(self, client: LLMClient, package_root: str = "kombu"):
        self.client = client
        self.package_root = package_root

    def run(self, repo_root: str, cycle: Dict) -> str:
        """Run the full pipeline on one cycle dict."""
        log_section("Pipeline start")
        nodes: List[str] = cycle["nodes"]
        edges: List[Dict] = cycle["edges"]
        log_line(f"Cycle ID: {cycle.get('id', '<no id>')} | length={cycle.get('length', len(nodes))}", Ansi.GRAY)
        log_line(f"Nodes: {nodes}", Ansi.GRAY)
        log_line(f"Edges: {[ (e['source'], '→', e['target']) for e in edges ]}", Ansi.GRAY)

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
        log_section("Dependency Expert A (A→B)", "magenta")
        dep_expert_A = DependencyExpertA("Dependency_Expert_A", self.client)
        dependency_summaries_A: Dict[str, Tuple[str, str]] = {} # key: a_path, content: (b_path, summary_a)
        for i, e in enumerate(edges, 1):
            a_node, b_node = e["source"], e["target"]
            a_path = default_node_to_path(repo_root, self.package_root, a_node)
            b_path = default_node_to_path(repo_root, self.package_root, b_node)
            log_line(f"[A:{i}] {a_node} → {b_node}", Ansi.MAGENTA)
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
            log_line(f"[B:{i}] {a_node} → {b_node}", Ansi.YELLOW)
            dep_summary_b = dep_expert_B.summarize_dependency(
                a_path, b_path, files[b_path], dependency_summaries_A[a_path][1],
            )
            dependency_summaries_B[a_path] = (b_path, dep_summary_b)

        # 3) Cycle_Expert → final prompt
        log_section("Cycle Expert (propose refactoring prompt)", "green")
        refactoring_expert = RefactoringExpert("Refactoring_Expert", self.client)
        #cycle_expert = CycleExpert("Cycle_Expert", self.client)
        final_prompt = refactoring_expert.propose(dependency_summaries_A, dependency_summaries_B)
        return final_prompt

# -------------------------
# Example usage
# -------------------------

if __name__ == "__main__":
    # Adjust these to your environment
    #LLM_URL = "http://localhost:1234/v1/chat/completions"
    #LLM_URL = "http://host.docker.internal:1234/v1/chat/completions" # LM studio (when running in docker)
    LLM_URL = "http://host.docker.internal:8000/v1/chat/completions" # UiO fox cluster (when running in docker)

    #API_KEY = "lm-studio"  # LM Studio default
    API_KEY = "token"  # LM Studio default
    MODEL = "Qwen/Qwen3-Coder-30B-A3B-Instruct" # "mistralai/Devstral-Small-2507" # "mistralai/magistral-small-2509" # "meta-llama/Llama-3.1-70B-Instruct"  # "google/gemma-3-12b" / your 24B devstral id

    # Repo root: path to your local kombu checkout (folder containing 'kombu/' package)
    REPO_ROOT = "../projects_to_analyze/click"

    # Example cycle (connection <-> messaging) — or use your transport/* example
    cycle_kombu = {
        "id": "scc_demo",
        "length": 2,
        "nodes": ["connection", "messaging"],
        "edges": [
            {"source": "connection", "target": "messaging", "relation": "module_dep"},
            {"source": "messaging", "target": "connection", "relation": "module_dep"},
        ],
        "summary": "Representative cycle of length 2",
    }

    cycle_tinydb = {
        "id": "scc_0_cycle_0",
        "length": 2,
        "nodes": [
            "__init__",
            "database"
        ],
        "edges": [
            {
                "source": "__init__",
                "target": "database",
                "relation": "module_dep"
            },
            {
                "source": "database",
                "target": "__init__",
                "relation": "module_dep"
            }
        ],
        "summary": "Representative cycle of length 2"
    }

    cycle_click = {
        "id": "scc_0_cycle_0",
        "length": 2,
        "nodes": [
            "_compat",
            "_winconsole"
        ],
        "edges": [
            {
                "source": "_compat",
                "target": "_winconsole",
                "relation": "module_dep"
            },
            {
                "source": "_winconsole",
                "target": "_compat",
                "relation": "module_dep"
            }
        ],
        "summary": "Representative cycle of length 2"
    }

    cycle_werkzeug = {
        "id": "scc_0_cycle_0",
        "length": 5,
        "nodes": [
            "__init__",
            "datastructures/range",
            "datastructures/__init__",
            "urls",
            "serving"
        ],
        "edges": [
            {
                "source": "__init__",
                "target": "datastructures/range",
                "relation": "module_dep"
            },
            {
                "source": "datastructures/range",
                "target": "datastructures/__init__",
                "relation": "module_dep"
            },
            {
                "source": "datastructures/__init__",
                "target": "urls",
                "relation": "module_dep"
            },
            {
                "source": "urls",
                "target": "serving",
                "relation": "module_dep"
            },
            {
                "source": "serving",
                "target": "__init__",
                "relation": "module_dep"
            }
        ],
        "summary": "Representative cycle of length 5"
    }

    client = LLMClient(LLM_URL, API_KEY, MODEL, temperature=0.1, max_tokens=16384)
    orch = Orchestrator(client, package_root="src/click") # src/werkzeug

    try:
        prompt = orch.run(REPO_ROOT, cycle_click)
        log_section("FINAL REFACTORING PROMPT", "green")
        print(prompt)
        log_section("END", "green")
    except Exception as e:
        log_section("Pipeline error", "red")
        print(e)
