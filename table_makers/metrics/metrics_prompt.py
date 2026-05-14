from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.io_utils import path_exists


EXPLANATION_START_ANCHOR = (
    "- It is not enough to remove some imports/references: for the chosen broken edge, "
    "all relevant references must be removed."
)


def read_text_if_exists(path: Path) -> Optional[str]:
    if not path_exists(path):
        return None

    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def compute_explanation_length(prompt_path: Path) -> Optional[int]:
    """
    Return the number of explanation characters appended after the fixed base
    refactoring prompt.

    No-explanation runs normally return 0 when the prompt file exists and the
    anchor is present. Missing or malformed prompt files return None.
    """
    text = read_text_if_exists(prompt_path)
    if text is None:
        return None

    anchor_idx = text.rfind(EXPLANATION_START_ANCHOR)
    if anchor_idx == -1:
        return None

    explanation_text = text[anchor_idx + len(EXPLANATION_START_ANCHOR):].lstrip()
    return len(explanation_text)