from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Sequence

import yaml


@dataclass(frozen=True)
class PlannedMode:
    id: str
    label: str
    experiments: Sequence[str]


@dataclass(frozen=True)
class AnalysisPlan:
    modes: Dict[str, PlannedMode]


def _load_yaml(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return raw


def load_analysis_plan(path: Path) -> AnalysisPlan:
    raw = _load_yaml(path)

    modes_raw = raw.get("modes", [])
    if not isinstance(modes_raw, list):
        raise ValueError(f"{path}: 'modes' must be a list")

    modes: Dict[str, PlannedMode] = {}

    for i, item in enumerate(modes_raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: modes[{i}] must be a mapping")

        mode_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        experiments = item.get("experiments", [])

        if not mode_id:
            raise ValueError(f"{path}: modes[{i}].id must be a non-empty string")
        if not label:
            raise ValueError(f"{path}: modes[{i}].label must be a non-empty string")
        if not isinstance(experiments, list) or not experiments:
            raise ValueError(f"{path}: modes[{i}].experiments must be a non-empty list")
        if mode_id in modes:
            raise ValueError(f"{path}: duplicate mode id {mode_id!r}")

        cleaned_experiments = [str(x).strip() for x in experiments]
        if any(not x for x in cleaned_experiments):
            raise ValueError(f"{path}: modes[{i}].experiments contains an empty value")

        modes[mode_id] = PlannedMode(
            id=mode_id,
            label=label,
            experiments=cleaned_experiments,
        )

    return AnalysisPlan(modes=modes)