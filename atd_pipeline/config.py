from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


@dataclass(frozen=True)
class RepoSpec:
    repo: str
    base_branch: str
    entry: str
    language: str = "unknown"


@dataclass(frozen=True)
class CycleSpec:
    repo: str
    base_branch: str
    cycle_id: str


def read_repos(repos_file_path: Path) -> List[RepoSpec]:
    repo_specs: List[RepoSpec] = []
    for raw_line in repos_file_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3:
            raise ValueError(f"Bad repos.txt line (need >=3 cols): {raw_line}")
        repo_name, base_branch, entry_subdir = parts[0], parts[1], parts[2]
        language = parts[3] if len(parts) >= 4 else "unknown"
        repo_specs.append(RepoSpec(repo=repo_name, base_branch=base_branch, entry=entry_subdir, language=language))
    return repo_specs


def read_cycles(cycles_file_path: Path) -> List[CycleSpec]:
    cycle_specs: List[CycleSpec] = []
    for raw_line in cycles_file_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3:
            raise ValueError(f"Bad cycles file line (need >=3 cols): {raw_line}")
        cycle_specs.append(CycleSpec(repo=parts[0], base_branch=parts[1], cycle_id=parts[2]))
    return cycle_specs


def group_cycles_by_repo_and_branch(cycle_specs: List[CycleSpec]) -> Dict[Tuple[str, str], List[CycleSpec]]:
    grouped: Dict[Tuple[str, str], List[CycleSpec]] = {}
    for cycle_spec in cycle_specs:
        grouped.setdefault((cycle_spec.repo, cycle_spec.base_branch), []).append(cycle_spec)
    return grouped


@dataclass(frozen=True)
class LLMConfig:
    base_url: str  # must end with /v1
    api_key: str
    model_raw: str


@dataclass(frozen=True)
class OpenHandsConfig:
    image: str
    runtime_image: str
    max_iters: int
    commit_message: str


@dataclass(frozen=True)
class ModeSpec:
    id: str
    params: Dict[str, Any]


@dataclass(frozen=True)
class PipelineConfig:
    projects_dir: Path
    repos_file: Path
    cycles_file: Path
    results_root: Path
    experiment_id: str

    llm: LLMConfig
    openhands: OpenHandsConfig
    modes: List[ModeSpec]

    @staticmethod
    def load(config_file_path: Path, *, repo_root: Path) -> "PipelineConfig":
        raw = yaml.safe_load(config_file_path.read_text(encoding="utf-8"))

        def resolve_repo_root_relative(path_str: str) -> Path:
            return (repo_root / path_str).resolve()

        llm_raw = raw.get("llm") or {}
        openhands_raw = raw.get("openhands") or {}

        mode_specs: List[ModeSpec] = []
        for mode_raw in (raw.get("modes") or []):
            mode_specs.append(ModeSpec(id=str(mode_raw["id"]), params=dict(mode_raw.get("params") or {})))

        return PipelineConfig(
            projects_dir=resolve_repo_root_relative(str(raw["projects_dir"])),
            repos_file=resolve_repo_root_relative(str(raw["repos_file"])),
            cycles_file=resolve_repo_root_relative(str(raw["cycles_file"])),
            results_root=resolve_repo_root_relative(str(raw["results_root"])),
            experiment_id=str(raw["experiment_id"]),
            llm=LLMConfig(
                base_url=str(llm_raw["base_url"]),
                api_key=str(llm_raw.get("api_key", "placeholder")),
                model_raw=str(llm_raw["model_raw"]),
            ),
            openhands=OpenHandsConfig(
                image=str(openhands_raw.get("image", "docker.all-hands.dev/all-hands-ai/openhands:0.59")),
                runtime_image=str(openhands_raw.get("runtime_image", "docker.all-hands.dev/all-hands-ai/runtime:0.59-nikolaik")),
                max_iters=int(openhands_raw.get("max_iters", 100)),
                commit_message=str(openhands_raw.get("commit_message", "Refactor: break dependency cycle")),
            ),
            modes=mode_specs,
        )

    def select_modes(self, requested_mode_ids: Optional[List[str]]) -> List[ModeSpec]:
        if not requested_mode_ids:
            return list(self.modes)

        requested_set = set(requested_mode_ids)
        selected = [mode for mode in self.modes if mode.id in requested_set]
        missing = sorted(requested_set - {mode.id for mode in selected})
        if missing:
            raise ValueError(f"Unknown mode(s): {missing}. Known: {[m.id for m in self.modes]}")
        return selected


Task = Tuple[RepoSpec, CycleSpec, ModeSpec]


def build_tasks(pipeline_config: PipelineConfig, requested_mode_ids: Optional[List[str]] = None) -> List[Task]:
    repo_specs = read_repos(pipeline_config.repos_file)
    repo_by_name_and_branch = {(repo.repo, repo.base_branch): repo for repo in repo_specs}

    cycle_specs = read_cycles(pipeline_config.cycles_file)
    cycles_grouped = group_cycles_by_repo_and_branch(cycle_specs)

    missing_pairs = sorted([pair for pair in cycles_grouped.keys() if pair not in repo_by_name_and_branch])
    if missing_pairs:
        raise ValueError(
            "cycles_to_analyze.txt contains repo/base pairs not present in repos.txt: "
            + ", ".join([f"{repo}@{branch}" for repo, branch in missing_pairs])
        )

    selected_modes = pipeline_config.select_modes(requested_mode_ids)

    experiment_units: List[Task] = []
    for (repo_name, base_branch), cycles_for_repo in cycles_grouped.items():
        repo_spec = repo_by_name_and_branch[(repo_name, base_branch)]
        for cycle_spec in cycles_for_repo:
            for mode_spec in selected_modes:
                experiment_units.append((repo_spec, cycle_spec, mode_spec))

    return experiment_units
