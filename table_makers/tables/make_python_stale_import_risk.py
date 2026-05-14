from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

from core.io_utils import write_dataframe_csv
from core.table_utils import build_mode_label_map, load_all_runs_df, present_mode_ids


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = REPO_ROOT / "projects_to_analyze"

SUMMARY_COLUMNS = [
    "mode_id",
    "Configuration",
    "Behavior-failed Python runs",
    "Runs with stale old import",
    "Runs with stale local reference after move",
    "Runs with removed import still used",
    "Runs with any stale reference risk",
    "Any stale reference risk (%)",
]


@dataclass(frozen=True)
class Hunk:
    old_start: int
    lines: Sequence[str]


@dataclass(frozen=True)
class FilePatch:
    old_path: Optional[str]
    new_path: Optional[str]
    removed_lines: Sequence[str]
    added_lines: Sequence[str]
    hunks: Sequence[Hunk]


@dataclass(frozen=True)
class RemovedSymbol:
    symbol: str
    removal_kind: str
    old_file: str
    old_module: str
    new_file: Optional[str]
    new_module: Optional[str]


@dataclass(frozen=True)
class RemovedImport:
    local_name: str
    old_file: str
    old_module: Optional[str]


@dataclass(frozen=True)
class StaleReferenceFinding:
    risk_type: str
    symbol: str
    removal_kind: str
    old_module: Optional[str]
    new_module: Optional[str]
    old_file: Optional[str]
    new_file: Optional[str]
    affected_file: str
    affected_line: int


TOP_LEVEL_DEF_RE = re.compile(
    r"^(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[\(:]"
)

HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_ast(text: str) -> Optional[ast.AST]:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _clean_diff_path(token: str) -> Optional[str]:
    token = token.strip()
    if token == "/dev/null":
        return None
    if token.startswith(("a/", "b/")):
        token = token[2:]
    return token or None


def _parse_patch(patch_path: Path) -> List[FilePatch]:
    text = _safe_read_text(patch_path)
    if not text:
        return []

    patches: List[FilePatch] = []

    old_path: Optional[str] = None
    new_path: Optional[str] = None
    removed_lines: List[str] = []
    added_lines: List[str] = []
    hunks: List[Hunk] = []

    current_hunk_start: Optional[int] = None
    current_hunk_lines: List[str] = []

    def flush_hunk() -> None:
        nonlocal current_hunk_start, current_hunk_lines

        if current_hunk_start is not None:
            hunks.append(
                Hunk(
                    old_start=current_hunk_start,
                    lines=tuple(current_hunk_lines),
                )
            )

        current_hunk_start = None
        current_hunk_lines = []

    def flush_file() -> None:
        nonlocal old_path, new_path, removed_lines, added_lines, hunks

        flush_hunk()

        if old_path is not None or new_path is not None:
            patches.append(
                FilePatch(
                    old_path=old_path,
                    new_path=new_path,
                    removed_lines=tuple(removed_lines),
                    added_lines=tuple(added_lines),
                    hunks=tuple(hunks),
                )
            )

        old_path = None
        new_path = None
        removed_lines = []
        added_lines = []
        hunks = []

    for line in text.splitlines():
        if line.startswith("diff --git "):
            flush_file()
            parts = line.split()
            if len(parts) >= 4:
                old_path = _clean_diff_path(parts[2])
                new_path = _clean_diff_path(parts[3])
            continue

        if line.startswith("--- "):
            old_path = _clean_diff_path(line.split(maxsplit=1)[1])
            continue

        if line.startswith("+++ "):
            new_path = _clean_diff_path(line.split(maxsplit=1)[1])
            continue

        match = HUNK_HEADER_RE.match(line)
        if match:
            flush_hunk()
            current_hunk_start = int(match.group(1))
            current_hunk_lines = []
            continue

        if line.startswith("\\ No newline at end of file"):
            continue

        if current_hunk_start is not None:
            current_hunk_lines.append(line)

        if line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])

    flush_file()
    return patches


def _entry_path(repo_root: Path, entry: str) -> Path:
    return repo_root / entry


def _import_root_for_entry(repo_root: Path, entry: str) -> Path:
    entry_path = _entry_path(repo_root, entry)

    if (entry_path / "__init__.py").exists():
        return entry_path.parent

    return entry_path


def _module_name_for_repo_file(
    *,
    repo_root: Path,
    import_root: Path,
    repo_file: str,
) -> Optional[str]:
    if not repo_file.endswith(".py"):
        return None

    try:
        rel = (repo_root / repo_file).relative_to(import_root)
    except ValueError:
        return None

    parts = list(rel.with_suffix("").parts)

    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    if not parts:
        return None

    return ".".join(parts)


def _module_name_for_source_file(
    *,
    import_root: Path,
    source_file: Path,
) -> Optional[str]:
    if source_file.suffix != ".py":
        return None

    try:
        rel = source_file.relative_to(import_root)
    except ValueError:
        return None

    parts = list(rel.with_suffix("").parts)

    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    if not parts:
        return None

    return ".".join(parts)


def _repo_rel_path(repo_root: Path, path: Path) -> Optional[str]:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return None


def _apply_patch_to_baseline_text(
    baseline_text: str,
    patch: FilePatch,
) -> Optional[str]:
    if patch.new_path is None:
        return None

    baseline_lines = baseline_text.splitlines()
    out: List[str] = []
    old_index = 0

    for hunk in patch.hunks:
        hunk_old_index = max(0, hunk.old_start - 1)

        if hunk_old_index < old_index or hunk_old_index > len(baseline_lines):
            return None

        out.extend(baseline_lines[old_index:hunk_old_index])
        old_index = hunk_old_index

        for line in hunk.lines:
            if not line:
                continue

            kind = line[0]
            value = line[1:]

            if kind == " ":
                if old_index >= len(baseline_lines):
                    return None
                if baseline_lines[old_index] != value:
                    return None
                out.append(value)
                old_index += 1

            elif kind == "-":
                if old_index >= len(baseline_lines):
                    return None
                if baseline_lines[old_index] != value:
                    return None
                old_index += 1

            elif kind == "+":
                out.append(value)

    out.extend(baseline_lines[old_index:])
    return "\n".join(out) + ("\n" if baseline_text.endswith("\n") else "")


def _post_texts_for_modified_python_files(
    *,
    repo_root: Path,
    patches: Sequence[FilePatch],
) -> Tuple[Dict[str, str], Set[str], Set[str]]:
    post_texts: Dict[str, str] = {}
    changed_files: Set[str] = set()
    unreconstructable_files: Set[str] = set()

    for patch in patches:
        for path in (patch.old_path, patch.new_path):
            if path and path.endswith(".py"):
                changed_files.add(path)

        if not patch.new_path or not patch.new_path.endswith(".py"):
            continue

        if patch.old_path is None:
            baseline_text = ""
        elif patch.old_path.endswith(".py") and (repo_root / patch.old_path).exists():
            baseline_text = _safe_read_text(repo_root / patch.old_path)
        else:
            unreconstructable_files.add(patch.new_path)
            continue

        post_text = _apply_patch_to_baseline_text(baseline_text, patch)
        if post_text is None:
            unreconstructable_files.add(patch.new_path)
            continue

        post_texts[patch.new_path] = post_text

    return post_texts, changed_files, unreconstructable_files


def _source_files_to_scan(
    *,
    repo_root: Path,
    source_root: Path,
    post_texts: Dict[str, str],
    changed_files: Set[str],
    unreconstructable_files: Set[str],
) -> List[str]:
    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
    }

    out: Set[str] = set()

    if source_root.exists():
        for path in source_root.rglob("*.py"):
            if any(part in skip_dirs for part in path.parts):
                continue

            rel = _repo_rel_path(repo_root, path)
            if rel is None:
                continue

            if rel in unreconstructable_files:
                continue

            if rel in changed_files and rel not in post_texts:
                continue

            out.add(rel)

    out.update(post_texts.keys())
    out.difference_update(unreconstructable_files)

    return sorted(out)


def _post_or_baseline_text(
    *,
    repo_root: Path,
    rel_path: str,
    post_texts: Dict[str, str],
) -> str:
    if rel_path in post_texts:
        return post_texts[rel_path]
    return _safe_read_text(repo_root / rel_path)


def _assigned_names(node: ast.AST) -> Set[str]:
    if isinstance(node, ast.Name):
        return {node.id}

    if isinstance(node, (ast.Tuple, ast.List)):
        names: Set[str] = set()
        for item in node.elts:
            names.update(_assigned_names(item))
        return names

    return set()


def _top_level_symbols_from_lines(lines: Sequence[str]) -> Set[str]:
    symbols: Set[str] = set()

    for line in lines:
        if line.startswith((" ", "\t")):
            continue

        match = TOP_LEVEL_DEF_RE.match(line)
        if match:
            symbols.add(match.group(1))

    return symbols


def _top_level_exported_names(text: str) -> Set[str]:
    tree = _parse_ast(text)
    if tree is None:
        return set()

    names: Set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_assigned_names(target))

        elif isinstance(node, ast.AnnAssign):
            names.update(_assigned_names(node.target))

        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])

        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)

    return names


def _bound_names_anywhere(text: str) -> Set[str]:
    tree = _parse_ast(text)
    if tree is None:
        return set()

    names: Set[str] = set()

    def add_args(args: ast.arguments) -> None:
        for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            names.add(arg.arg)
        if args.vararg is not None:
            names.add(args.vararg.arg)
        if args.kwarg is not None:
            names.add(args.kwarg.arg)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            add_args(node.args)

        elif isinstance(node, ast.Lambda):
            add_args(node.args)

        elif isinstance(node, ast.ClassDef):
            names.add(node.name)

        elif isinstance(node, ast.arg):
            names.add(node.arg)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])

        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_assigned_names(target))

        elif isinstance(node, ast.AnnAssign):
            names.update(_assigned_names(node.target))

        elif isinstance(node, ast.AugAssign):
            names.update(_assigned_names(node.target))

        elif isinstance(node, (ast.For, ast.AsyncFor)):
            names.update(_assigned_names(node.target))

        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    names.update(_assigned_names(item.optional_vars))

        elif isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            names.add(node.name)

    return names


def _runtime_name_load_lines(text: str, symbol: str) -> List[int]:
    tree = _parse_ast(text)
    if tree is None:
        return []

    lines: Set[int] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Load) and node.id == symbol:
                line_no = int(getattr(node, "lineno", 0) or 0)
                if line_no:
                    lines.add(line_no)

        def visit_arg(self, node: ast.arg) -> None:
            return

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if node.value is not None:
                self.visit(node.value)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def _visit_function(self, node) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in node.args.defaults:
                self.visit(default)
            for default in node.args.kw_defaults:
                if default is not None:
                    self.visit(default)
            for stmt in node.body:
                self.visit(stmt)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            for default in node.args.defaults:
                self.visit(default)
            for default in node.args.kw_defaults:
                if default is not None:
                    self.visit(default)
            self.visit(node.body)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword)
            for stmt in node.body:
                self.visit(stmt)

        def visit_Import(self, node: ast.Import) -> None:
            return

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            return

    Visitor().visit(tree)
    return sorted(lines)


def _is_init_file(path: Path) -> bool:
    return path.name == "__init__.py"


def _resolve_from_import_module(
    *,
    current_module: str,
    current_file: Path,
    imported_module: Optional[str],
    level: int,
) -> Optional[str]:
    if level == 0:
        return imported_module

    if _is_init_file(current_file):
        package = current_module
    else:
        package = current_module.rsplit(".", 1)[0] if "." in current_module else ""

    package_parts = package.split(".") if package else []
    drops = max(0, level - 1)

    if drops > len(package_parts):
        return None

    parts = package_parts[: len(package_parts) - drops]

    if imported_module:
        parts.extend(imported_module.split("."))

    if not parts:
        return None

    return ".".join(parts)


def _from_import_lines(
    *,
    text: str,
    source_file: Path,
    import_root: Path,
    target_module: str,
    symbol: str,
) -> List[int]:
    tree = _parse_ast(text)
    if tree is None:
        return []

    current_module = _module_name_for_source_file(
        import_root=import_root,
        source_file=source_file,
    )
    if current_module is None:
        return []

    lines: Set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue

        resolved_module = _resolve_from_import_module(
            current_module=current_module,
            current_file=source_file,
            imported_module=node.module,
            level=node.level,
        )

        if resolved_module != target_module:
            continue

        for alias in node.names:
            if alias.name == symbol:
                line_no = int(getattr(node, "lineno", 0) or 0)
                if line_no:
                    lines.add(line_no)

    return sorted(lines)


def _has_from_import(
    *,
    text: str,
    source_file: Path,
    import_root: Path,
    target_module: str,
    symbol: str,
) -> bool:
    return bool(
        _from_import_lines(
            text=text,
            source_file=source_file,
            import_root=import_root,
            target_module=target_module,
            symbol=symbol,
        )
    )


def _removed_imports_from_patch(patches: Sequence[FilePatch]) -> List[RemovedImport]:
    out: List[RemovedImport] = []

    for patch in patches:
        if not patch.old_path or not patch.old_path.endswith(".py"):
            continue

        removed_import_lines = [
            line
            for line in patch.removed_lines
            if line.startswith("import ") or line.startswith("from ")
        ]

        if not removed_import_lines:
            continue

        tree = _parse_ast("\n".join(removed_import_lines))
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    out.append(
                        RemovedImport(
                            local_name=alias.asname or alias.name.split(".", 1)[0],
                            old_file=patch.old_path,
                            old_module=alias.name,
                        )
                    )

            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        continue

                    out.append(
                        RemovedImport(
                            local_name=alias.asname or alias.name,
                            old_file=patch.old_path,
                            old_module=node.module,
                        )
                    )

    seen: Set[Tuple[str, str, Optional[str]]] = set()
    unique: List[RemovedImport] = []

    for item in out:
        key = (item.local_name, item.old_file, item.old_module)
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def _find_removed_symbols(
    *,
    patches: Sequence[FilePatch],
    repo_root: Path,
    import_root: Path,
    post_texts: Dict[str, str],
) -> List[RemovedSymbol]:
    removed_defs: Dict[str, List[Tuple[str, str]]] = {}
    added_defs: Dict[str, List[Tuple[str, str]]] = {}

    for patch in patches:
        old_module = None
        new_module = None

        if patch.old_path:
            old_module = _module_name_for_repo_file(
                repo_root=repo_root,
                import_root=import_root,
                repo_file=patch.old_path,
            )

        if patch.new_path:
            new_module = _module_name_for_repo_file(
                repo_root=repo_root,
                import_root=import_root,
                repo_file=patch.new_path,
            )

        if patch.old_path and old_module:
            for symbol in _top_level_symbols_from_lines(patch.removed_lines):
                removed_defs.setdefault(symbol, []).append((patch.old_path, old_module))

        if patch.new_path and new_module:
            for symbol in _top_level_symbols_from_lines(patch.added_lines):
                added_defs.setdefault(symbol, []).append((patch.new_path, new_module))

    out: List[RemovedSymbol] = []

    for symbol in sorted(removed_defs):
        for old_file, old_module in removed_defs[symbol]:
            post_old_text = post_texts.get(old_file)

            if post_old_text is not None and symbol in _top_level_exported_names(post_old_text):
                continue

            moved_targets = [
                (new_file, new_module)
                for new_file, new_module in added_defs.get(symbol, [])
                if new_module != old_module
                and new_file in post_texts
                and symbol in _top_level_exported_names(post_texts[new_file])
            ]

            if moved_targets:
                for new_file, new_module in moved_targets:
                    out.append(
                        RemovedSymbol(
                            symbol=symbol,
                            removal_kind="moved",
                            old_file=old_file,
                            old_module=old_module,
                            new_file=new_file,
                            new_module=new_module,
                        )
                    )
            else:
                out.append(
                    RemovedSymbol(
                        symbol=symbol,
                        removal_kind="deleted",
                        old_file=old_file,
                        old_module=old_module,
                        new_file=None,
                        new_module=None,
                    )
                )

    seen: Set[Tuple[str, str, str, Optional[str], Optional[str]]] = set()
    unique: List[RemovedSymbol] = []

    for item in out:
        key = (
            item.symbol,
            item.removal_kind,
            item.old_file,
            item.new_file,
            item.new_module,
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def _detect_stale_reference_findings_for_run(row: pd.Series) -> List[StaleReferenceFinding]:
    repo = str(row.get("repo", "")).strip()
    entry = str(row.get("entry", "")).strip()
    patch_path = Path(str(row.get("diff_patch_path", "")))

    if not repo or not entry or not patch_path.exists():
        return []

    repo_root = PROJECTS_DIR / repo
    source_root = _entry_path(repo_root, entry)
    import_root = _import_root_for_entry(repo_root, entry)

    if not repo_root.exists() or not source_root.exists():
        return []

    patches = _parse_patch(patch_path)
    if not patches:
        return []

    post_texts, changed_files, unreconstructable_files = _post_texts_for_modified_python_files(
        repo_root=repo_root,
        patches=patches,
    )

    scan_files = _source_files_to_scan(
        repo_root=repo_root,
        source_root=source_root,
        post_texts=post_texts,
        changed_files=changed_files,
        unreconstructable_files=unreconstructable_files,
    )

    removed_symbols = _find_removed_symbols(
        patches=patches,
        repo_root=repo_root,
        import_root=import_root,
        post_texts=post_texts,
    )
    removed_imports = _removed_imports_from_patch(patches)

    findings: List[StaleReferenceFinding] = []

    for removed in removed_symbols:
        for rel_path in scan_files:
            text = _post_or_baseline_text(
                repo_root=repo_root,
                rel_path=rel_path,
                post_texts=post_texts,
            )
            if not text:
                continue

            for line_no in _from_import_lines(
                text=text,
                source_file=repo_root / rel_path,
                import_root=import_root,
                target_module=removed.old_module,
                symbol=removed.symbol,
            ):
                findings.append(
                    StaleReferenceFinding(
                        risk_type="stale_old_import",
                        symbol=removed.symbol,
                        removal_kind=removed.removal_kind,
                        old_module=removed.old_module,
                        new_module=removed.new_module,
                        old_file=removed.old_file,
                        new_file=removed.new_file,
                        affected_file=rel_path,
                        affected_line=line_no,
                    )
                )

    for removed in removed_symbols:
        if removed.removal_kind != "moved" or removed.new_module is None:
            continue

        post_old_text = post_texts.get(removed.old_file)
        if post_old_text is None:
            continue

        if _has_from_import(
            text=post_old_text,
            source_file=repo_root / removed.old_file,
            import_root=import_root,
            target_module=removed.new_module,
            symbol=removed.symbol,
        ):
            continue

        if removed.symbol in _bound_names_anywhere(post_old_text):
            continue

        for line_no in _runtime_name_load_lines(post_old_text, removed.symbol):
            findings.append(
                StaleReferenceFinding(
                    risk_type="stale_local_reference_after_move",
                    symbol=removed.symbol,
                    removal_kind=removed.removal_kind,
                    old_module=removed.old_module,
                    new_module=removed.new_module,
                    old_file=removed.old_file,
                    new_file=removed.new_file,
                    affected_file=removed.old_file,
                    affected_line=line_no,
                )
            )

    for removed_import in removed_imports:
        post_text = post_texts.get(removed_import.old_file)
        if post_text is None:
            continue

        if removed_import.local_name in _bound_names_anywhere(post_text):
            continue

        for line_no in _runtime_name_load_lines(post_text, removed_import.local_name):
            findings.append(
                StaleReferenceFinding(
                    risk_type="removed_import_still_used",
                    symbol=removed_import.local_name,
                    removal_kind="import_removed",
                    old_module=removed_import.old_module,
                    new_module=None,
                    old_file=removed_import.old_file,
                    new_file=None,
                    affected_file=removed_import.old_file,
                    affected_line=line_no,
                )
            )

    return findings


def _pct(numer: int, denom: int) -> Optional[float]:
    if denom == 0:
        return None
    return round(100.0 * numer / denom, 1)


def build_python_stale_import_risk_rows(all_runs_csv_path: Path) -> pd.DataFrame:
    df = load_all_runs_df(all_runs_csv_path)

    if df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    required = [
        "mode_id",
        "mode_label",
        "repo",
        "entry",
        "language",
        "behavior_preserved",
        "diff_patch_path",
    ]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            "Cannot build Python stale-reference-risk table because all_runs.csv "
            "is missing columns: " + ", ".join(missing)
        )

    labels: Dict[str, str] = build_mode_label_map(df)
    mode_ids = present_mode_ids(df)

    summary_rows: List[Dict[str, object]] = []

    for mode_id in mode_ids:
        mode_df = df[df["mode_id"] == mode_id].copy()

        failed_python_df = mode_df[
            (mode_df["language"].astype(str).str.lower() == "python")
            & (
                pd.to_numeric(mode_df["behavior_preserved"], errors="coerce")
                .fillna(0)
                .astype(int)
                == 0
            )
        ].copy()

        behavior_failed_python_runs = int(len(failed_python_df))

        stale_old_import = 0
        stale_local_reference_after_move = 0
        removed_import_still_used = 0
        any_stale_reference = 0

        for _, run in failed_python_df.iterrows():
            findings = _detect_stale_reference_findings_for_run(run)
            risk_types = {finding.risk_type for finding in findings}

            if "stale_old_import" in risk_types:
                stale_old_import += 1

            if "stale_local_reference_after_move" in risk_types:
                stale_local_reference_after_move += 1

            if "removed_import_still_used" in risk_types:
                removed_import_still_used += 1

            if findings:
                any_stale_reference += 1

        summary_rows.append(
            {
                "mode_id": mode_id,
                "Configuration": labels.get(mode_id, mode_id),
                "Behavior-failed Python runs": behavior_failed_python_runs,
                "Runs with stale old import": stale_old_import,
                "Runs with stale local reference after move": stale_local_reference_after_move,
                "Runs with removed import still used": removed_import_still_used,
                "Runs with any stale reference risk": any_stale_reference,
                "Any stale reference risk (%)": _pct(
                    any_stale_reference,
                    behavior_failed_python_runs,
                ),
            }
        )

    return pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS)


def write_python_stale_import_risk_csv(
    all_runs_csv_path: Path,
    outdir: Path,
) -> Path:
    summary_df = build_python_stale_import_risk_rows(all_runs_csv_path)

    summary_path = outdir / "python_stale_import_risk.csv"
    write_dataframe_csv(summary_path, summary_df)

    return summary_path