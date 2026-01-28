from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List

from agent_setup import LLMClient
from agent_util import read_file


def extract_refactoring_prompt(text: str) -> str:
    m = re.search(r"<<<BEGIN_REFACTORING_PROMPT>>>(.*?)<<<END_REFACTORING_PROMPT>>>", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def node_to_abs(repo_root: str, node_id: str) -> str:
    # node_id is repo-relative file path from dependency_graph.json
    return os.path.join(repo_root, node_id)


@dataclass(frozen=True)
class CycleContext:
    repo_root: str
    src_root: str
    cycle: Dict

    @property
    def nodes(self) -> List[str]:
        return [str(n) for n in (self.cycle.get("nodes") or [])]

    @property
    def edges(self) -> List[Dict]:
        return list(self.cycle.get("edges") or [])

    def read_cycle_files(self) -> Dict[str, str]:
        files: Dict[str, str] = {}
        for node in self.nodes:
            p = node_to_abs(self.repo_root, node)
            if not os.path.exists(p):
                raise FileNotFoundError(f"Missing cycle node on disk: {node} -> {p}")
            files[p] = read_file(p)
        return files


class OrchestratorBase(ABC):
    """
    Each orchestrator implements a different multi-agent structure.
    It should return *only* the OpenHands-ready instruction part (not the base minimal template).
    The entrypoint will prepend the minimal base template consistently.
    """

    def __init__(self, client: LLMClient):
        self.client = client

    @abstractmethod
    def run(self, ctx: CycleContext, *, refactor_prompt_variant: str) -> str:
        raise NotImplementedError
