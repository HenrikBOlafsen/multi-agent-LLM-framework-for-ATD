#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import requests

REPO_ROOT = Path("projects_to_analyze")
REPOS_FILE = Path("repos.txt")

MIN_STARS = 1000
MIN_LOC = 4000
MAX_DAYS = 365  # ~6 months

# Optional: avoid GitHub API rate limits
# export GITHUB_TOKEN=...
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Map your repos.txt language tokens to cloc language names
CLOC_LANG_MAP = {
    "python": "Python",
    "csharp": "C#",
}

# Choose which upstream to use for star count:
# - "parent": immediate upstream
# - "source": root/original repo (often what people mean by “upstream”)
UPSTREAM_KIND_FOR_STARS = "source"


def run(cmd: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)


def parse_owner_repo_from_remote(url: str) -> Optional[Tuple[str, str]]:
    """
    Supports:
      - https://github.com/owner/repo(.git)
      - git@github.com:owner/repo(.git)
    """
    url = url.strip()

    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)

    m = re.match(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)

    return None


def get_owner_repo(local_repo_path: Path) -> Optional[Tuple[str, str]]:
    p = run(["git", "remote", "get-url", "origin"], cwd=local_repo_path)
    if p.returncode != 0:
        return None
    return parse_owner_repo_from_remote(p.stdout.strip())


def github_get(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=20)


def get_upstream_stars(owner: str, repo: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Returns (stars, stars_repo_full_name, error).

    If repo is a fork and GitHub provides 'parent'/'source', returns stars for upstream
    according to UPSTREAM_KIND_FOR_STARS.
    Otherwise returns stars for the repo itself.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}"
    r = github_get(url)
    if r.status_code != 200:
        return None, None, f"GitHub repo API {r.status_code}: {r.text[:200]}"

    j = r.json()

    if j.get("fork"):
        upstream_obj = j.get(UPSTREAM_KIND_FOR_STARS) or j.get("parent") or j.get("source")
        if upstream_obj:
            return upstream_obj.get("stargazers_count"), upstream_obj.get("full_name"), None

    return j.get("stargazers_count"), j.get("full_name"), None


def get_last_commit_date(owner: str, repo: str, branch: str) -> Tuple[Optional[dt.datetime], Optional[str]]:
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    r = github_get(url)
    if r.status_code != 200:
        return None, f"GitHub commit API {r.status_code}: {r.text[:200]}"

    date_str = r.json()["commit"]["committer"]["date"]
    commit_dt = dt.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    return commit_dt, None


def recent_enough(commit_dt: dt.datetime) -> bool:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - commit_dt).days <= MAX_DAYS


def get_loc(local_repo_path: Path, src_rel_path: str, lang_token: str) -> Tuple[Optional[int], Optional[str]]:
    cloc_lang = CLOC_LANG_MAP.get(lang_token.lower())
    if not cloc_lang:
        return None, f"Unknown language token '{lang_token}' (add to CLOC_LANG_MAP)"

    src_path = local_repo_path / src_rel_path
    if not src_path.exists():
        return None, f"Path not found: {src_path}"

    cmd = [
        "cloc",
        str(src_path),
        f"--include-lang={cloc_lang}",
        "--quiet",
        "--json",
    ]
    p = run(cmd)
    if p.returncode != 0:
        return None, f"cloc failed: {p.stderr.strip()[:200]}"

    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None, "Failed to parse cloc JSON output"

    # With --include-lang, SUM should reflect just that language
    if "SUM" in data and "code" in data["SUM"]:
        return int(data["SUM"]["code"]), None

    # Fallback if cloc returns language key
    if cloc_lang in data and "code" in data[cloc_lang]:
        return int(data[cloc_lang]["code"]), None

    return 0, None


def check_one(line: str) -> dict:
    repo_name, branch, src_rel, lang = line.split()

    local_repo_path = REPO_ROOT / repo_name
    if not local_repo_path.exists():
        return {"repo": repo_name, "passed": False, "error": f"Local repo folder not found: {local_repo_path}"}

    owner_repo = get_owner_repo(local_repo_path)
    if not owner_repo:
        return {
            "repo": repo_name,
            "passed": False,
            "error": "Could not parse owner/repo from git origin remote (missing origin? not cloned?)",
        }

    owner, gh_repo = owner_repo

    stars, stars_repo_full_name, stars_err = get_upstream_stars(owner, gh_repo)
    commit_dt, commit_err = get_last_commit_date(owner, gh_repo, branch)
    loc, loc_err = get_loc(local_repo_path, src_rel, lang)

    stars_ok = (stars is not None) and (stars >= MIN_STARS)
    commit_ok = (commit_dt is not None) and recent_enough(commit_dt)
    loc_ok = (loc is not None) and (loc >= MIN_LOC)

    return {
        "repo": repo_name,
        "owner": owner,
        "gh_repo": gh_repo,
        "branch": branch,
        "src": src_rel,
        "lang": lang,
        "stars": stars,
        "stars_repo": stars_repo_full_name,
        "last_commit": commit_dt.isoformat() if commit_dt else None,
        "loc": loc,
        "stars_ok": stars_ok,
        "commit_ok": commit_ok,
        "loc_ok": loc_ok,
        "passed": stars_ok and commit_ok and loc_ok,
        "errors": [e for e in [stars_err, commit_err, loc_err] if e],
    }


def main():
    lines = [
        l.strip()
        for l in REPOS_FILE.read_text().splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]

    for line in lines:
        res = check_one(line)

        if "error" in res:
            print(f"FAIL | {res['repo']} | {res['error']}")
            continue

        status = "PASS" if res["passed"] else "FAIL"
        errs = (" | " + " ; ".join(res["errors"])) if res["errors"] else ""

        print(
            f"{status} | {res['repo']} "
            f"(fork={res['owner']}/{res['gh_repo']}) "
            f"| stars={res['stars']} (from {res['stars_repo']}) "
            f"| loc={res['loc']} "
            f"| last_commit={res['last_commit']}"
            f"{errs}"
        )


if __name__ == "__main__":
    main()