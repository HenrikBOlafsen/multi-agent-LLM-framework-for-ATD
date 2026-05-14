from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.io_utils import path_exists, read_json


def _extract_usage_from_entry(entry: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """
    Extract (prompt_tokens, completion_tokens) from a single trajectory entry.

    Expected shape:
      entry["llm_metrics"]["accumulated_token_usage"]["prompt_tokens"]
      entry["llm_metrics"]["accumulated_token_usage"]["completion_tokens"]
    """
    llm_metrics = entry.get("llm_metrics")
    if not isinstance(llm_metrics, dict):
        return None

    usage = llm_metrics.get("accumulated_token_usage")
    if not isinstance(usage, dict):
        return None

    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")

    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        return None

    return prompt_tokens, completion_tokens


def read_token_metrics_from_trajectory(
    trajectory_path: Path,
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Returns:
        (prompt_tokens, completion_tokens, total_tokens)

    Rules:
    - Reads openhands/trajectory.json
    - Uses the LAST entry in the trajectory
    - Pulls token counts from llm_metrics.accumulated_token_usage
    - total_tokens = prompt_tokens + completion_tokens
    - Returns (None, None, None) if the file is missing or malformed
    """
    if not path_exists(trajectory_path):
        return None, None, None

    try:
        data = read_json(trajectory_path)
    except Exception:
        return None, None, None

    if not isinstance(data, list) or not data:
        return None, None, None

    last_entry = data[-1]
    if not isinstance(last_entry, dict):
        return None, None, None

    usage = _extract_usage_from_entry(last_entry)
    if usage is None:
        return None, None, None

    prompt_tokens, completion_tokens = usage
    total_tokens = prompt_tokens + completion_tokens
    return prompt_tokens, completion_tokens, total_tokens