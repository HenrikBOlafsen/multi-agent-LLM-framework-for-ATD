from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from core.io_utils import read_yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


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
class PipelineInputs:
    projects_dir: Path
    repos_file: Path
    cycles_file: Path
    results_root: Path


def load_pipeline_inputs(config_path: Path) -> PipelineInputs:
    raw = read_yaml(config_path)

    def need_str(key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{config_path}: missing or invalid string field {key!r}")
        return value.strip()

    return PipelineInputs(
        projects_dir=(REPO_ROOT / need_str("projects_dir")).resolve(),
        repos_file=(REPO_ROOT / need_str("repos_file")).resolve(),
        cycles_file=(REPO_ROOT / need_str("cycles_file")).resolve(),
        results_root=(REPO_ROOT / need_str("results_root")).resolve(),
    )


def read_repos_file(path: Path) -> List[RepoSpec]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: List[RepoSpec] = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 4:
            raise ValueError(f"Bad repos file line (expected 4 columns): {line}")

        out.append(
            RepoSpec(
                repo=parts[0],
                base_branch=parts[1],
                entry=parts[2],
                language=parts[3],
            )
        )

    return out


def read_cycles_file(path: Path) -> List[CycleSpec]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: List[CycleSpec] = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"Bad cycles file line (expected 3 columns): {line}")

        out.append(
            CycleSpec(
                repo=parts[0],
                base_branch=parts[1],
                cycle_id=parts[2],
            )
        )

    return out