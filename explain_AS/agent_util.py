import os

def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def default_node_to_path(repo_root: str, package_root: str, node: str) -> str:
    """
    Maps a node like 'connection.py' -> kombu/connection.py
                    'transport/__init__.py' -> kombu/transport/__init__.py
                    'transport/librabbitmq.py' -> kombu/transport/librabbitmq.py
    Adjust `package_root` if your nodes are not rooted at 'kombu'.
    """
    parts = node.split("/")
    return os.path.join(repo_root, package_root, *parts)

def clip(text: str, max_chars: int = 100000) -> str:
    """Safety clip for very large files"""
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return head + "\n...\n# [snip]\n...\n" + tail