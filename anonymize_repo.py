#!/usr/bin/env python3
"""
anonymize_repo.py

Recursively replace sensitive strings across a directory tree, with safety rails.
Now supports selecting files by exact name (--names) or glob patterns (--name-glob).

Key features:
- Target specific filenames (e.g., status.json, pip_freeze.txt) for speed/safety
- Optional extension whitelist and directory exclude patterns
- Skips obvious binary/huge files (unless --force-binary)
- Dry-run, backups, case-insensitive/whole-word matching
- Clear summary of changes

Examples
--------
Only edit status.json and pip_freeze.txt:
    python anonymize_repo.py --root . \
        --find "HenrikBOlafsen" --replace "Anonymous" \
        --names status.json pip_freeze.txt --backup

Use globs instead (all *.json named “status.json” anywhere):
    python anonymize_repo.py --root . \
        --find "HenrikBOlafsen" --replace "Anonymous" \
        --name-glob "status.json" --backup

Dry run first:
    python anonymize_repo.py --root . \
        --find "HenrikBOlafsen" --replace "Anonymous" \
        --names status.json pip_freeze.txt --dry-run

Case-insensitive + whole-word:
    python anonymize_repo.py --root . \
        --find "henrikbolafsen" --replace "Anonymous" \
        --names status.json pip_freeze.txt --ignore-case --whole-word
"""

from __future__ import annotations
import argparse
import os
import re
from pathlib import Path
import fnmatch
import sys

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".mypy_cache", "__pycache__", ".venv", "venv",
    ".idea", ".vscode", "node_modules", "dist", "build", ".ruff_cache",
    ".pytest_cache", ".DS_Store", ".ipynb_checkpoints", ".cache"
}

BINARY_EXTS = {
    ".png",".jpg",".jpeg",".gif",".bmp",".ico",".tiff",".tif",".webp",
    ".mp3",".mp4",".mov",".avi",".mkv",".wav",".flac",
    ".pdf",".zip",".tar",".gz",".tgz",".xz",".7z",".rar",
    ".so",".dll",".dylib",".o",".a",".class",".jar",
    ".pt",".bin",".safetensors"
}

def is_probably_binary(path: Path, size_limit_mb: int = 50) -> bool:
    if path.suffix.lower() in BINARY_EXTS:
        return True
    try:
        size = path.stat().st_size
        if size > size_limit_mb * 1024 * 1024:
            return True
        with path.open("rb") as f:
            chunk = f.read(4096)
            if b"\x00" in chunk:
                return True
    except Exception:
        return True
    return False

def build_regex(find: str, ignore_case: bool, whole_word: bool) -> re.Pattern:
    flags = re.MULTILINE
    if ignore_case:
        flags |= re.IGNORECASE
    pattern = re.escape(find)
    if whole_word:
        pattern = r"\b" + pattern + r"\b"
    return re.compile(pattern, flags)

def replacer_in_text(text: str, regex: re.Pattern, replace: str) -> tuple[str, int]:
    new_text, n = regex.subn(replace, text)
    return new_text, n

def process_file(path: Path, regex: re.Pattern, replace: str, dry_run: bool, backup: bool, force_binary: bool) -> int:
    if not force_binary and is_probably_binary(path):
        return 0
    try:
        raw = path.read_bytes()
    except Exception:
        return 0
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return 0

    new_text, n = replacer_in_text(text, regex, replace)
    if n > 0 and not dry_run:
        if backup:
            bak = path.with_suffix(path.suffix + ".bak")
            try:
                bak.write_bytes(raw)
            except Exception:
                pass
        path.write_text(new_text, encoding="utf-8", newline="")
    return n

def should_skip_dir(dirname: str, extra_excludes: set[str]) -> bool:
    base = os.path.basename(dirname)
    return base in DEFAULT_EXCLUDE_DIRS or base in extra_excludes

def name_matches(basename: str, names: set[str] | None, name_globs: list[str] | None) -> bool:
    if names:
        if basename in names:
            return True
    if name_globs:
        for pat in name_globs:
            if fnmatch.fnmatch(basename, pat):
                return True
        return False
    # if neither filter is set, accept everything (other filters may still apply)
    return names is None and name_globs is None

def walk_files(root: Path, exts: set[str] | None, exclude_dirs: set[str],
               names: set[str] | None, name_globs: list[str] | None) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d, exclude_dirs)]
        for fn in filenames:
            if not name_matches(fn, names, name_globs):
                continue
            p = Path(dirpath) / fn
            if exts is not None:
                # if extensions are also provided, they act as an additional filter
                if p.suffix in exts or (p.name in exts):  # allow bare names like Dockerfile
                    files.append(p)
            else:
                files.append(p)
    return files

def main():
    ap = argparse.ArgumentParser(description="Recursively replace sensitive strings in a project tree.")
    ap.add_argument("--root", type=Path, required=True, help="Root directory to process.")
    ap.add_argument("--find", required=True, help="String to find.")
    ap.add_argument("--replace", required=True, help="Replacement string.")
    ap.add_argument("--ext", nargs="*", default=None, help="Optional whitelist of file extensions or filenames.")
    ap.add_argument("--names", nargs="*", default=None, help="Exact basenames to process (e.g., status.json pip_freeze.txt).")
    ap.add_argument("--name-glob", nargs="*", default=None, help="Glob patterns for basenames (e.g., '*.json', 'status.json').")
    ap.add_argument("--exclude-dirs", nargs="*", default=[], help="Extra directories to exclude (names only).")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files.")
    ap.add_argument("--backup", action="store_true", help="Write .bak alongside modified files.")
    ap.add_argument("--ignore-case", action="store_true", help="Case-insensitive match.")
    ap.add_argument("--whole-word", action="store_true", help="Match whole words only.")
    ap.add_argument("--force-binary", action="store_true", help="Attempt replacements in binary/large files too (not recommended).")
    args = ap.parse_args()

    root: Path = args.root
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Root path not found or not a directory: {root}", file=sys.stderr)
        sys.exit(2)

    exts = None
    if args.ext:
        norm = set()
        for e in args.ext:
            if not e.startswith(".") and "." in e:
                e = "." + e.split(".")[-1]
            norm.add(e if e.startswith(".") else e)  # keep bare filenames like Dockerfile
        exts = norm

    names_set = set(args.names) if args.names else None
    name_globs = args.name_glob  # list[str] | None

    exclude_dirs = set(args.exclude_dirs)
    regex = build_regex(args.find, args.ignore_case, args.whole_word)

    files = walk_files(root, exts, exclude_dirs, names_set, name_globs)

    total_files = 0
    total_hits = 0
    changed_files = []

    for p in files:
        hits = process_file(p, regex, args.replace, args.dry_run, args.backup, args.force_binary)
        if hits > 0:
            total_files += 1
            total_hits += hits
            changed_files.append((p, hits))

    if args.dry_run:
        print(f"[DRY-RUN] Files that would be changed: {total_files}")
        for p, hits in changed_files[:200]:
            print(f"  {p}  (+{hits} replacements)")
        if len(changed_files) > 200:
            print(f"  ...and {len(changed_files) - 200} more")
    else:
        print(f"[DONE] Files changed: {total_files}, total replacements: {total_hits}")
        for p, hits in changed_files[:200]:
            print(f"  {p}  (+{hits})")
        if len(changed_files) > 200:
            print(f"  ...and {len(changed_files) - 200} more")

if __name__ == "__main__":
    main()
