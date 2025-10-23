import os

def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def default_node_to_path(repo_root: str, package_root: str, node: str) -> str:
    """
    Join repo_root + package_root + node, but avoid double-rooting.
    If node already starts with package_root/, strip it first.
    Examples:
    repo_root=".../kombu", package_root="kombu", node="kombu/connection.py"
        -> .../kombu/kombu/connection.py
    repo_root=".../kombu", package_root="kombu", node="connection.py"
        -> .../kombu/kombu/connection.py
    """
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