from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml


def _die(msg: str) -> None:
    raise ValueError(msg)


def _need(d: Dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        _die(f"Missing required config field: {where}.{key}")
    return d[key]


def _need_int(d: Dict[str, Any], key: str, where: str) -> int:
    v = _need(d, key, where)
    if not isinstance(v, int):
        _die(f"Config field must be int: {where}.{key} (got {type(v).__name__})")
    return int(v)


def _need_str(d: Dict[str, Any], key: str, where: str) -> str:
    v = _need(d, key, where)
    if not isinstance(v, str) or not v.strip():
        _die(f"Config field must be non-empty string: {where}.{key}")
    return v.strip()


def _opt_int(d: Dict[str, Any], key: str, where: str) -> Optional[int]:
    if key not in d:
        return None
    v = d[key]
    if v is None:
        return None
    if not isinstance(v, int):
        _die(f"Config field must be int: {where}.{key} (got {type(v).__name__})")
    return int(v)


def _opt_str(d: Dict[str, Any], key: str, where: str) -> Optional[str]:
    if key not in d:
        return None
    v = d[key]
    if v is None:
        return None
    if not isinstance(v, str):
        _die(f"Config field must be string: {where}.{key} (got {type(v).__name__})")
    return v.strip()


@dataclass(frozen=True)
class RepoSpec:
    repo: str
    base_branch: str
    entry: str
    language: str


@dataclass(frozen=True)
class CycleSpec:
    repo: str
    base_branch: str
    cycle_id: str


@dataclass(frozen=True)
class ModeSpec:
    id: str
    params: Dict[str, Any]


@dataclass(frozen=True)
class PolicyConfig:
    delete_refactor_branches_after_metrics: bool


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model_raw: str
    context_length: int  # REQUIRED, no default, no backwards-compat


@dataclass(frozen=True)
class OpenHandsConfig:
    image: str
    runtime_image: str
    max_iters: int
    commit_message: str


@dataclass(frozen=True)
class PipelineConfig:
    projects_dir: Path
    repos_file: Path
    cycles_file: Path
    results_root: Path
    experiment_id: str

    policy: PolicyConfig
    llm: LLMConfig
    openhands: OpenHandsConfig

    modes: List[ModeSpec]

    @staticmethod
    def load(config_path: Path, *, repo_root: Path) -> "PipelineConfig":
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            _die(f"Bad YAML root in {config_path}: expected mapping")

        projects_dir = (repo_root / Path(_need_str(raw, "projects_dir", "root"))).resolve()
        repos_file = (repo_root / Path(_need_str(raw, "repos_file", "root"))).resolve()
        cycles_file = (repo_root / Path(_need_str(raw, "cycles_file", "root"))).resolve()
        results_root = (repo_root / Path(_need_str(raw, "results_root", "root"))).resolve()
        experiment_id = _need_str(raw, "experiment_id", "root")

        # policy
        policy_raw = raw.get("policy")
        if not isinstance(policy_raw, dict):
            _die("Missing required config field: policy (mapping)")
        delete_branches = policy_raw.get("delete_refactor_branches_after_metrics")
        if not isinstance(delete_branches, bool):
            _die("Config field must be bool: policy.delete_refactor_branches_after_metrics")
        policy = PolicyConfig(delete_refactor_branches_after_metrics=delete_branches)

        # llm
        llm_raw = raw.get("llm")
        if not isinstance(llm_raw, dict):
            _die("Missing required config field: llm (mapping)")
        llm = LLMConfig(
            base_url=_need_str(llm_raw, "base_url", "llm"),
            api_key=_need_str(llm_raw, "api_key", "llm"),
            model_raw=_need_str(llm_raw, "model_raw", "llm"),
            context_length=_need_int(llm_raw, "context_length", "llm"),
        )

        # openhands
        oh_raw = raw.get("openhands")
        if not isinstance(oh_raw, dict):
            _die("Missing required config field: openhands (mapping)")
        openhands = OpenHandsConfig(
            image=_need_str(oh_raw, "image", "openhands"),
            runtime_image=_need_str(oh_raw, "runtime_image", "openhands"),
            max_iters=_need_int(oh_raw, "max_iters", "openhands"),
            commit_message=_need_str(oh_raw, "commit_message", "openhands"),
        )

        # modes
        modes_raw = raw.get("modes")
        if not isinstance(modes_raw, list) or not modes_raw:
            _die("Missing required config field: modes (non-empty list)")
        modes: List[ModeSpec] = []
        for i, m in enumerate(modes_raw):
            if not isinstance(m, dict):
                _die(f"Bad modes[{i}]: expected mapping")
            mid = _need_str(m, "id", f"modes[{i}]")
            params = m.get("params") or {}
            if not isinstance(params, dict):
                _die(f"Bad modes[{i}].params: expected mapping")
            modes.append(ModeSpec(id=mid, params=params))

        return PipelineConfig(
            projects_dir=projects_dir,
            repos_file=repos_file,
            cycles_file=cycles_file,
            results_root=results_root,
            experiment_id=experiment_id,
            policy=policy,
            llm=llm,
            openhands=openhands,
            modes=modes,
        )


def read_repos(repos_file: Path) -> List[RepoSpec]:
    lines = repos_file.read_text(encoding="utf-8").splitlines()
    out: List[RepoSpec] = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) < 4:
            _die(f"Bad repos.txt line (expected 4 columns): {ln}")
        out.append(RepoSpec(repo=parts[0], base_branch=parts[1], entry=parts[2], language=parts[3]))
    return out


def read_cycles(cycles_file: Path) -> List[CycleSpec]:
    lines = cycles_file.read_text(encoding="utf-8").splitlines()
    out: List[CycleSpec] = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) < 3:
            _die(f"Bad cycles file line (expected 3 columns): {ln}")
        out.append(CycleSpec(repo=parts[0], base_branch=parts[1], cycle_id=parts[2]))
    return out


def build_tasks(pipeline_config: PipelineConfig, modes: Optional[Sequence[str]]) -> List[Tuple[RepoSpec, CycleSpec, ModeSpec]]:
    repo_specs = {r.repo: r for r in read_repos(pipeline_config.repos_file)}
    cycle_specs = read_cycles(pipeline_config.cycles_file)

    selected_modes: List[ModeSpec]
    if modes is None:
        selected_modes = list(pipeline_config.modes)
    else:
        want = set(modes)
        selected_modes = [m for m in pipeline_config.modes if m.id in want]
        if not selected_modes:
            _die(f"No modes matched --modes {sorted(want)} (available: {[m.id for m in pipeline_config.modes]})")

    tasks: List[Tuple[RepoSpec, CycleSpec, ModeSpec]] = []
    for cyc in cycle_specs:
        repo = repo_specs.get(cyc.repo)
        if repo is None:
            _die(f"cycles_file references unknown repo '{cyc.repo}' (not present in repos_file)")
        # sanity: base branch should match between files
        if repo.base_branch != cyc.base_branch:
            _die(f"Base branch mismatch for repo {cyc.repo}: repos_file has {repo.base_branch}, cycles_file has {cyc.base_branch}")
        for mode in selected_modes:
            tasks.append((repo, cyc, mode))
    return tasks
