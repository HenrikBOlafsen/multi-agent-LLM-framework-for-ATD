#!/usr/bin/env python3
import csv
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

REPOS_FILE = Path("repos_all.txt")
ROOT = Path("projects_to_analyze")

REPO_OUT = Path("repo_selection_stats.csv")
SUMMARY_OUT = Path("repo_selection_summary.csv")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


def run(cmd, cwd=None):
    return subprocess.check_output(
        cmd,
        cwd=cwd,
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def github_repo_from_remote(remote_url: str):
    remote_url = remote_url.strip()

    patterns = [
        r"github\.com[:/](.+?)/(.+?)(?:\.git)?$",
        r"https://github\.com/(.+?)/(.+?)(?:\.git)?$",
    ]

    for pattern in patterns:
        match = re.search(pattern, remote_url)
        if match:
            owner, repo = match.group(1), match.group(2)
            return owner, repo.removesuffix(".git")

    return None, None


def github_api(path):
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "repo-selection-stats-script",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def get_remote_url(repo_path: Path):
    """
    Prefer upstream if available, because origin may be a personal fork.
    Fall back to origin otherwise.
    """
    try:
        return "upstream", run(["git", "remote", "get-url", "upstream"], cwd=repo_path)
    except subprocess.CalledProcessError:
        return "origin", run(["git", "remote", "get-url", "origin"], cwd=repo_path)


def get_stars_repo(owner: str, repo: str):
    """
    If the configured GitHub repository is a fork, use the source repository
    for the star count. Otherwise, use the repository itself.
    """
    info = github_api(f"/repos/{owner}/{repo}")

    if info.get("fork") and info.get("source"):
        source = info["source"]
        return (
            source["owner"]["login"],
            source["name"],
            source["stargazers_count"],
            True,
        )

    return owner, repo, info["stargazers_count"], False


def count_nonblank_loc(repo_path: Path, entry_dir: str, language: str):
    base = repo_path / entry_dir

    if language == "python":
        extensions = {".py"}
    elif language == "csharp":
        extensions = {".cs"}
    else:
        raise ValueError(f"Unsupported language: {language}")

    excluded_dirs = {
        ".git",
        "bin",
        "obj",
        "build",
        "dist",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "packages",
    }

    total = 0

    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if any(part in excluded_dirs for part in path.parts):
            continue
        if path.suffix not in extensions:
            continue

        lower_name = path.name.lower()
        if language == "csharp" and (
            lower_name.endswith(".g.cs")
            or lower_name.endswith(".designer.cs")
            or lower_name.endswith(".assemblyinfo.cs")
        ):
            continue

        try:
            with path.open("r", encoding="utf-8", errors="ignore") as file:
                total += sum(1 for line in file if line.strip())
        except OSError:
            continue

    return total


def language_sort_key(language: str):
    """
    Keep Python repositories first, then C#/.NET repositories.
    Unknown languages are placed after the known groups.
    """
    order = {
        "python": 0,
        "csharp": 1,
    }
    return order.get(language, 99)


def row_sort_key(row):
    """
    Sort alphabetically within each language group.
    Casefolding makes the ordering stable regardless of capitalization.
    """
    return (
        language_sort_key(row["language"]),
        row["repo"].casefold(),
    )


def summarize(rows, label, language=None):
    if language is None:
        selected = rows
    else:
        selected = [row for row in rows if row["language"] == language]

    if not selected:
        raise ValueError(f"No rows available for summary group: {label}")

    stars = [int(row["stars"]) for row in selected]
    locs = [int(row["loc_nonblank"]) for row in selected]

    return {
        "group": label,
        "repositories": len(selected),
        "stars_median": int(round(median(stars))),
        "stars_min": min(stars),
        "stars_max": max(stars),
        "loc_median": int(round(median(locs))),
        "loc_min": min(locs),
        "loc_max": max(locs),
    }


def main():
    rows = []

    stats_collected_at = datetime.now(timezone.utc)
    stats_collected_date = stats_collected_at.date().isoformat()
    stats_collected_at_utc = stats_collected_at.isoformat()

    with REPOS_FILE.open() as file:
        for raw_line in file:
            raw_line = raw_line.strip()

            if not raw_line or raw_line.startswith("#"):
                continue

            name, branch, entry_dir, language = raw_line.split()
            repo_path = ROOT / name

            if not repo_path.exists():
                raise FileNotFoundError(f"Repository directory not found: {repo_path}")

            remote_name, remote_url = get_remote_url(repo_path)
            owner, repo = github_repo_from_remote(remote_url)

            if owner is None:
                raise RuntimeError(
                    f"Could not parse GitHub repository from {remote_name} remote "
                    f"for {name}: {remote_url}"
                )

            stars_owner, stars_repo, stars, stars_from_source_repo = get_stars_repo(
                owner, repo
            )

            commit_hash = run(["git", "rev-parse", "HEAD"], cwd=repo_path)
            commit_date_raw = run(
                ["git", "show", "-s", "--format=%cI", commit_hash],
                cwd=repo_path,
            )
            commit_date = datetime.fromisoformat(
                commit_date_raw.replace("Z", "+00:00")
            ).date().isoformat()

            loc_nonblank = count_nonblank_loc(repo_path, entry_dir, language)

            row = {
                "repo": name,
                "language": language,
                "entry_dir": entry_dir,
                "stars": stars,
                "loc_nonblank": loc_nonblank,
                "commit_hash": commit_hash,
                "commit_date": commit_date,
                "github_remote_repo": f"{owner}/{repo}",
                "github_stars_repo": f"{stars_owner}/{stars_repo}",
                "stars_from_source_repo": stars_from_source_repo,
                "listed_branch": branch,
                "remote_name": remote_name,
                "remote_url": remote_url,
                "stats_collected_date": stats_collected_date,
                "stats_collected_at_utc": stats_collected_at_utc,
            }

            rows.append(row)

            source_note = "source" if stars_from_source_repo else "repo"
            print(
                f"{name:30s} "
                f"stars={stars:7d} "
                f"loc={loc_nonblank:7d} "
                f"commit={commit_hash[:12]} "
                f"{source_note}={stars_owner}/{stars_repo}"
            )

    if not rows:
        raise RuntimeError(f"No repositories found in {REPOS_FILE}")

    rows.sort(key=row_sort_key)

    with REPO_OUT.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    summary_rows = [
        summarize(rows, "Python", "python"),
        summarize(rows, "C#/.NET", "csharp"),
        summarize(rows, "All"),
    ]

    with SUMMARY_OUT.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=summary_rows[0].keys())
        writer.writeheader()
        writer.writerows(summary_rows)

    print("\nSummary")
    print(f"Statistics collected at: {stats_collected_at_utc}")
    print(f"Repositories: {len(rows)}")
    print(f"Wrote: {REPO_OUT}")
    print(f"Wrote: {SUMMARY_OUT}")


if __name__ == "__main__":
    main()