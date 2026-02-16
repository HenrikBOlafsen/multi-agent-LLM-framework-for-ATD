import os


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def default_node_to_path(repo_root: str, package_root: str, node: str) -> str:
    pkg = (package_root or "").strip("/").strip()
    rel = node.lstrip("./")
    if pkg and (rel == pkg or rel.startswith(pkg + "/")):
        rel = rel[len(pkg):].lstrip("/")
    parts = rel.split("/") if rel else []
    return os.path.join(repo_root, *( [pkg] if pkg else [] ), *parts)


def clip(text: str, max_chars: int = 50000) -> str:
    """Safety clip for very large files"""
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return head + "\n...\n# [snip]\n...\n" + tail


def clip_middle(text: str, *, max_chars: int) -> str:
    """
    Keep both beginning and end (useful for prompts that have instructions at top + code at bottom).
    """
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return head + "\n...\n# [snip]\n...\n" + tail
