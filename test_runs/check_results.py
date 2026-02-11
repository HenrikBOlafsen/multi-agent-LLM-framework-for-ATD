#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def read_text_lines(p: Path) -> list[str]:
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]


def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def must_exist(p: Path, why: str) -> None:
    if not p.exists():
        raise SystemExit(f"Missing {why}: {p}")


def must_nonempty(p: Path, why: str) -> None:
    must_exist(p, why)
    if p.stat().st_size == 0:
        raise SystemExit(f"Empty {why}: {p}")


def main(case_dir: Path) -> None:
    cfg_path = case_dir / "pipeline.yaml"
    exp_path = case_dir / "expected.json"
    must_exist(cfg_path, "case pipeline.yaml")
    must_exist(exp_path, "expected.json")

    cfg = load_yaml(cfg_path)
    expected = json.loads(exp_path.read_text(encoding="utf-8"))

    results_root = Path(cfg["results_root"]).resolve()
    repos_file = Path(cfg["repos_file"]).resolve()
    cycles_file = Path(cfg["cycles_file"]).resolve()

    must_exist(results_root, "results_root directory")
    must_exist(repos_file, "repos_file")
    must_exist(cycles_file, "cycles_file")

    # Parse repos
    repos = []
    for ln in read_text_lines(repos_file):
        parts = ln.split()
        if len(parts) < 4:
            raise SystemExit(f"Bad repos.txt line: {ln}")
        repo, base_branch, entry, language = parts[0], parts[1], parts[2], parts[3]
        repos.append((repo, base_branch, entry, language))

    # Parse cycles
    cycles = []
    for ln in read_text_lines(cycles_file):
        parts = ln.split()
        if len(parts) < 3:
            raise SystemExit(f"Bad cycles_to_analyze line: {ln}")
        cycles.append((parts[0], parts[1], parts[2]))

    # Baseline checks (per repo)
    for repo, base_branch, _entry, _language in repos:
        base_dir = results_root / repo / "branches" / base_branch
        atd_dir = base_dir / "ATD_identification"
        qc_dir = base_dir / "code_quality_checks"

        must_nonempty(atd_dir / "dependency_graph.json", f"{repo}@{base_branch} dependency_graph.json")
        must_nonempty(atd_dir / "scc_report.json", f"{repo}@{base_branch} scc_report.json")

        # metrics.json should exist; contents may have nulls
        must_nonempty(qc_dir / "metrics.json", f"{repo}@{base_branch} code_quality_checks/metrics.json")

        # Optional sanity: schema_version + language field exists
        mj = json.loads((qc_dir / "metrics.json").read_text(encoding="utf-8"))
        if "schema_version" not in mj or "language" not in mj:
            raise SystemExit(f"metrics.json missing schema_version/language for {repo}@{base_branch}: {qc_dir / 'metrics.json'}")

    # Explain checks (per cycle and mode)
    modes = expected.get("expect_modes", [])
    if not modes:
        raise SystemExit("expected.json must include expect_modes")

    for repo, base_branch, cycle_id in cycles:
        for mode in modes:
            # Your branch naming includes experiment_id; we can reconstruct the refactor branch name
            exp_id = str(cfg["experiment_id"])
            refactor_branch = f"atd-{exp_id}-{mode}-{cycle_id}".replace(" ", "-")
            branch_dir = results_root / repo / "branches" / refactor_branch
            prompt_path = branch_dir / "explain" / "prompt.txt"

            must_nonempty(prompt_path, f"prompt.txt for {repo} {mode} {cycle_id}")

    print("All checks passed.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 test_runs/check_results.py <case_dir>")
    main(Path(sys.argv[1]).resolve())
