from __future__ import annotations

from pathlib import Path
from typing import Optional, Set, Tuple

from core.io_utils import path_exists


def read_patch_if_exists(path: Path) -> Optional[str]:
    if not path_exists(path):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def compute_diff_metrics(patch_path: Path) -> Tuple[Optional[int], Optional[int]]:
    """
    Returns:
        (files_modified, chars_changed)

    Rules:
    - files_modified = number of unique files touched by the patch
    - chars_changed = sum of characters in added (+) and removed (-) lines,
      excluding diff metadata lines
    """
    text = read_patch_if_exists(patch_path)
    if text is None:
        return None, None

    files: Set[str] = set()
    chars_changed = 0

    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                a_path = parts[2]
                b_path = parts[3]

                for token in (a_path, b_path):
                    if token == "/dev/null":
                        continue
                    if token.startswith("a/") or token.startswith("b/"):
                        token = token[2:]
                    if token:
                        files.add(token)
            continue

        if line.startswith("+++ ") or line.startswith("--- "):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                token = parts[1].strip()
                if token != "/dev/null":
                    if token.startswith("a/") or token.startswith("b/"):
                        token = token[2:]
                    if token:
                        files.add(token)
            continue

        if (
            line.startswith("@@")
            or line.startswith("index ")
            or line.startswith("new file mode ")
            or line.startswith("deleted file mode ")
            or line.startswith("similarity index ")
            or line.startswith("rename from ")
            or line.startswith("rename to ")
        ):
            continue

        if line.startswith("+") and not line.startswith("+++"):
            chars_changed += len(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            chars_changed += len(line[1:])

    return len(files), chars_changed