#!/usr/bin/env python3
"""
Simple declarative case checker for the ATD pipeline (no pytest).

Usage:
  python3 test_runs/check_case.py test_runs/cases/<case_dir>

Expects in <case_dir>:
  - pipeline.yaml
  - expected.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import yaml


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def die(msg: str) -> None:
    raise SystemExit(f"❌ {msg}")


def read_lines(p: Path) -> List[str]:
    return [
        ln.strip()
        for ln in p.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def load_yaml(p: Path) -> Dict[str, Any]:
    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception as e:
        die(f"Bad YAML {p}: {e}")


def load_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception as e:
        die(f"Bad JSON {p}: {e}")


# ------------------------------------------------------------
# Branch name (match pipeline)
# ------------------------------------------------------------

_re_bad = re.compile(r"[^A-Za-z0-9._/-]+")
_re_dash = re.compile(r"-{2,}")


def sanitize_branch(s: str) -> str:
    s = s.strip().replace(" ", "-")
    s = _re_bad.sub("-", s)
    s = _re_dash.sub("-", s)
    return s.strip("-").rstrip("/")


def make_branch(exp_id: str, mode: str, cycle: str) -> str:
    b = sanitize_branch(f"atd-{exp_id}-{mode}-{cycle}")
    if not b:
        die("Branch name became empty after sanitation")
    return b


# ------------------------------------------------------------
# Filesystem checks
# ------------------------------------------------------------

def glob_paths(p: str) -> List[Path]:
    if any(c in p for c in "*?[]"):
        return [Path(x) for x in glob.glob(p)]
    return [Path(p)]


def must_exist(p: str, why: str) -> Path:
    matches = glob_paths(p)

    if not matches:
        die(f"{why}: no matches for {p}")

    path = matches[0]

    if not path.exists():
        die(f"{why}: missing {path}")

    return path


def must_nonempty(p: str, why: str) -> Path:
    path = must_exist(p, why)

    if path.stat().st_size == 0:
        die(f"{why}: empty {path}")

    return path


# ------------------------------------------------------------
# JSON checks
# ------------------------------------------------------------

def lookup(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def assert_json(path: Path, rule: Dict, label: str) -> None:
    data = load_json(path)

    key = rule.get("key")
    if not key:
        die(f"{label}: json_assert missing key")

    val = lookup(data, key)

    if rule.get("exists") is True:
        if val is None:
            die(f"{label}: {key} missing in {path}")
        return

    if "equals" in rule:
        if val != rule["equals"]:
            die(f"{label}: {path}: {key} != {rule['equals']} (got {val})")
        return

    if "in" in rule:
        if val not in rule["in"]:
            die(f"{label}: {path}: {key} not in {rule['in']} (got {val})")
        return

    if "contains" in rule:
        if not isinstance(val, str) or rule["contains"] not in val:
            die(f"{label}: {path}: {key} does not contain {rule['contains']}")
        return

    die(f"{label}: bad json_assert rule {rule}")


# ------------------------------------------------------------
# Git
# ------------------------------------------------------------

def git_branch_exists(repo: Path, branch: str) -> bool:
    rc = subprocess.run(
        ["git", "-C", str(repo),
         "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode

    return rc == 0


# ------------------------------------------------------------
# Input parsing
# ------------------------------------------------------------

def read_repos(p: Path) -> List[Dict[str, str]]:
    out = []

    for ln in read_lines(p):
        parts = ln.split()
        if len(parts) < 4:
            die(f"Bad repos.txt line: {ln}")

        out.append({
            "repo": parts[0],
            "base_branch": parts[1],
            "entry": parts[2],
            "language": parts[3],
        })

    return out


def read_cycles(p: Path) -> List[Dict[str, str]]:
    out = []

    for ln in read_lines(p):
        parts = ln.split()
        if len(parts) < 3:
            die(f"Bad cycles file line: {ln}")

        out.append({
            "repo": parts[0],
            "base_branch": parts[1],
            "cycle_id": parts[2],
        })

    return out


# ------------------------------------------------------------
# Templates
# ------------------------------------------------------------

def fmt(tpl: str, ctx: Dict[str, str]) -> str:
    try:
        return tpl.format(**ctx)
    except KeyError as e:
        die(f"Template {tpl} uses unknown {e}")


def apply_block(block: Dict, ctx: Dict, label: str) -> None:

    for t in block.get("exists", []) or []:
        must_exist(fmt(t, ctx), f"{label} exists")

    for t in block.get("nonempty", []) or []:
        must_nonempty(fmt(t, ctx), f"{label} nonempty")

    for rule in block.get("json_assert", []) or []:
        p = Path(fmt(rule.get("path", ""), ctx))
        must_nonempty(str(p), f"{label} json")
        assert_json(p, rule, label)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_dir")
    args = ap.parse_args()

    case_dir = Path(args.case_dir).resolve()

    cfg_path = case_dir / "pipeline.yaml"
    exp_path = case_dir / "expected.json"

    if not cfg_path.exists():
        die(f"Missing {cfg_path}")

    if not exp_path.exists():
        die(f"Missing {exp_path}")

    cfg = load_yaml(cfg_path)
    exp = load_json(exp_path)

    # pipeline.yaml fields
    projects_dir = Path(cfg["projects_dir"]).resolve()
    results_root = Path(cfg["results_root"]).resolve()
    repos_file = Path(cfg["repos_file"]).resolve()
    cycles_file = Path(cfg["cycles_file"]).resolve()
    experiment_id = str(cfg["experiment_id"])

    if not experiment_id:
        die("experiment_id missing")

    # inputs
    repos = read_repos(repos_file)
    cycles = read_cycles(cycles_file)

    modes = exp.get("modes")
    if not isinstance(modes, list) or not modes:
        die("expected.json must contain modes: []")

    # --------------------------------------------------------
    # Baseline
    # --------------------------------------------------------

    baseline = exp.get("baseline") or {}

    if baseline:
        for r in repos:
            ctx = {
                "projects_dir": str(projects_dir),
                "results_root": str(results_root),
                "repo": r["repo"],
                "base_branch": r["base_branch"],
                "cycle_id": "",
                "mode": "",
                "branch": r["base_branch"],
            }

            apply_block(baseline, ctx, f"baseline {r['repo']}")

        print("✅ baseline OK")

    # --------------------------------------------------------
    # LLM / OpenHands
    # --------------------------------------------------------

    llm = exp.get("llm") or {}
    need_branch = bool(llm.get("git_branch_exists"))

    if llm:
        for c in cycles:
            for mode in modes:
                branch = make_branch(experiment_id, mode, c["cycle_id"])

                ctx = {
                    "projects_dir": str(projects_dir),
                    "results_root": str(results_root),
                    "repo": c["repo"],
                    "base_branch": c["base_branch"],
                    "cycle_id": c["cycle_id"],
                    "mode": mode,
                    "branch": branch,
                }

                apply_block(llm, ctx, f"llm {c['repo']} {mode}")

                if need_branch:
                    repo_dir = projects_dir / c["repo"]

                    if not git_branch_exists(repo_dir, branch):
                        die(f"Missing git branch {branch} in {repo_dir}")

        print("✅ llm OK")

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    metrics = exp.get("metrics") or {}

    if metrics:
        status_tpl = metrics.get("status_latest")

        if not status_tpl:
            die("metrics.status_latest missing")

        ok_if_committed = metrics.get("if_openhands_outcome_committed", "ok")
        otherwise = metrics.get("otherwise", "skipped")

        for c in cycles:
            for mode in modes:
                branch = make_branch(experiment_id, mode, c["cycle_id"])

                ctx = {
                    "projects_dir": str(projects_dir),
                    "results_root": str(results_root),
                    "repo": c["repo"],
                    "base_branch": c["base_branch"],
                    "cycle_id": c["cycle_id"],
                    "mode": mode,
                    "branch": branch,
                }

                oh_path = Path(fmt(
                    "{results_root}/{repo}/branches/{branch}/openhands/status_latest.json",
                    ctx
                ))

                must_nonempty(str(oh_path), "openhands status")

                oh = load_json(oh_path)
                oh_out = str(oh.get("outcome", ""))

                expect = ok_if_committed if oh_out == "committed" else otherwise

                ms_path = Path(fmt(status_tpl, ctx))
                must_nonempty(str(ms_path), "metrics status")

                ms = load_json(ms_path)
                got = str(ms.get("outcome", ""))

                if got != expect:
                    die(
                        f"metrics {c['repo']} {mode}: expected {expect}, "
                        f"got {got} (openhands={oh_out})"
                    )

        print("✅ metrics OK")

    print(f"\n🎉 Case passed: {case_dir}")


if __name__ == "__main__":
    main()
