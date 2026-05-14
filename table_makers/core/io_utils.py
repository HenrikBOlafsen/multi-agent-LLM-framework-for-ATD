from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import yaml


def path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_yaml(path: Path) -> Dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return raw


def write_dataframe_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def read_dataframe_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def pct(numer: int, denom: int) -> Optional[float]:
    if denom == 0:
        return None
    return round((100.0 * numer) / denom, 1)