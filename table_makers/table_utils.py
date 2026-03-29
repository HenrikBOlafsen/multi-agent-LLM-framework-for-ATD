#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml


@dataclass(frozen=True)
class RepoSpec:
    repo: str
    base_branch: str
    entry: str
    language: str


@dataclass(frozen=True)
class CycleSpec:
    repo: str
    base_branch: str
    cycle_id: str


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_json_any(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_pipeline_config(path: Path) -> Dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"Bad YAML root in {path}: expected mapping")
    return raw


def read_repos_file(path: Path) -> List[RepoSpec]:
    out: List[RepoSpec] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            raise SystemExit(f"Bad repos file line (expected 4 columns): {line}")
        out.append(
            RepoSpec(
                repo=parts[0],
                base_branch=parts[1],
                entry=parts[2],
                language=parts[3].lower(),
            )
        )
    return out


def read_cycles_file(path: Path) -> List[CycleSpec]:
    out: List[CycleSpec] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            raise SystemExit(f"Bad cycles file line (expected 3 columns): {line}")
        out.append(CycleSpec(repo=parts[0], base_branch=parts[1], cycle_id=parts[2]))
    return out


def resolve_config_relative_path(rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    return p.resolve() if not p.is_absolute() else p


def mode_ids_from_config(config: Dict[str, Any]) -> List[str]:
    modes = config.get("modes")
    if not isinstance(modes, list):
        return []
    out: List[str] = []
    for item in modes:
        if isinstance(item, dict):
            mode_id = item.get("id")
            if isinstance(mode_id, str) and mode_id.strip():
                out.append(mode_id.strip())
    return out


def choose_default_modes(available_mode_ids: Sequence[str]) -> Tuple[str, str]:
    if len(available_mode_ids) < 2:
        raise SystemExit("Need at least 2 modes in config to compare")

    ids = list(available_mode_ids)
    if "no_explain" in ids:
        others = [m for m in ids if m != "no_explain"]
        if not others:
            raise SystemExit("Config has only one usable mode")
        return ("no_explain", others[0])

    return (ids[0], ids[1])


def sanitize_git_branch_name(candidate: str) -> str:
    candidate = candidate.strip().replace(" ", "-")
    candidate = re.sub(r"[^A-Za-z0-9._/-]+", "-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-").rstrip("/")
    return candidate


def branch_for_run(experiment_id: str, mode_id: str, cycle_id: str) -> str:
    return sanitize_git_branch_name(f"atd-{experiment_id}-{mode_id}-{cycle_id}")


def results_dir_for_branch(results_root: Path, repo_name: str, branch_name: str) -> Path:
    return results_root / repo_name / "branches" / branch_name


def get_scc_metrics(scc_report: Dict[str, Any]) -> Dict[str, Any]:
    gm = scc_report["global_metrics"]
    return {
        "scc_count": gm.get("scc_count"),
        "max_scc_size": gm.get("max_scc_size"),
        "avg_scc_size": gm.get("avg_scc_size"),
        "total_nodes_in_cyclic_sccs": gm.get("total_nodes_in_cyclic_sccs"),
        "total_edges_in_cyclic_sccs": gm.get("total_edges_in_cyclic_sccs"),
        "total_loc_in_cyclic_sccs": gm.get("total_loc_in_cyclic_sccs"),
        "cycle_pressure_lb": gm.get("cycle_pressure_lb"),
    }


def get_test_counts(metrics_json: Optional[Dict[str, Any]], language: str) -> Optional[Dict[str, int]]:
    if not metrics_json:
        return None

    lang = language.strip().lower()
    block = metrics_json.get("pytest") if lang == "python" else metrics_json.get("dotnet_test")
    if not isinstance(block, dict):
        return None

    try:
        tests = int(block.get("tests"))
        failures = int(block.get("failures", 0) or 0)
        errors = int(block.get("errors", 0) or 0)
        skipped = int(block.get("skipped", 0) or 0)
    except Exception:
        return None

    if tests <= 0:
        return None

    passed = max(0, tests - failures - errors - skipped)
    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": passed,
    }


def strict_test_counts_ok(base: Optional[Dict[str, int]], post: Optional[Dict[str, int]]) -> bool:
    if not base or not post:
        return False
    try:
        return (
            int(post["failures"]) <= int(base["failures"])
            and int(post["errors"]) <= int(base["errors"])
            and int(post["skipped"]) <= int(base["skipped"])
            and int(post["passed"]) >= int(base["passed"])
        )
    except Exception:
        return False


def _int_or_none(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def get_explain_total_tokens(path: Path) -> Optional[int]:
    data = read_json(path)
    if not data:
        return None

    accum = data.get("accumulated_usage")
    if not isinstance(accum, dict):
        return None

    total = _int_or_none(accum.get("total_tokens"))
    if total is not None:
        return total

    prompt = _int_or_none(accum.get("prompt_tokens"))
    completion = _int_or_none(accum.get("completion_tokens"))
    if prompt is None or completion is None:
        return None
    return prompt + completion


def get_openhands_total_tokens(path: Path) -> Optional[int]:
    data = read_json_any(path)
    if not isinstance(data, list):
        return None

    for event in reversed(data):
        if not isinstance(event, dict):
            continue
        llm_metrics = event.get("llm_metrics")
        if not isinstance(llm_metrics, dict):
            continue
        accum = llm_metrics.get("accumulated_token_usage")
        if not isinstance(accum, dict):
            continue

        prompt = _int_or_none(accum.get("prompt_tokens"))
        completion = _int_or_none(accum.get("completion_tokens"))
        if prompt is not None and completion is not None:
            return prompt + completion

        total = _int_or_none(accum.get("total_tokens"))
        if total is not None:
            return total

    return None


def safe_sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        return float(a) - float(b)
    except Exception:
        return None


def _clean_numeric(vals: Iterable[Optional[float]]) -> List[float]:
    xs: List[float] = []
    for v in vals:
        if isinstance(v, (int, float)):
            vf = float(v)
            if not math.isnan(vf) and not math.isinf(vf):
                xs.append(vf)
    return xs


def mean_or_none(vals: Iterable[Optional[float]]) -> Optional[float]:
    xs = _clean_numeric(vals)
    return (sum(xs) / len(xs)) if xs else None


def std_or_none(vals: Iterable[Optional[float]]) -> Optional[float]:
    xs = _clean_numeric(vals)
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def median_or_none(vals: Iterable[Optional[float]]) -> Optional[float]:
    import statistics

    xs = _clean_numeric(vals)
    return float(statistics.median(xs)) if xs else None


def _find_cycle_size_recursive(obj: Any, cycle_id: str) -> Optional[int]:
    if isinstance(obj, dict):
        id_candidates = [obj.get("cycle_id"), obj.get("id"), obj.get("cycle"), obj.get("name")]
        if any(str(x) == str(cycle_id) for x in id_candidates if x is not None):
            for key in ("length", "size", "cycle_size"):
                val = obj.get(key)
                if isinstance(val, int):
                    return int(val)
            nodes = obj.get("nodes")
            if isinstance(nodes, list):
                return len(nodes)

        for v in obj.values():
            got = _find_cycle_size_recursive(v, cycle_id)
            if got is not None:
                return got

    elif isinstance(obj, list):
        for item in obj:
            got = _find_cycle_size_recursive(item, cycle_id)
            if got is not None:
                return got

    return None


def cycle_size_from_catalog(base_branch_dir: Path, cycle_id: str) -> Optional[int]:
    catalog = read_json(base_branch_dir / "ATD_identification" / "cycle_catalog.json")
    if not catalog:
        return None
    return _find_cycle_size_recursive(catalog, cycle_id)


def load_cycle_definition(base_branch_dir: Path, cycle_id: str) -> Optional[Dict[str, Any]]:
    catalog = read_json(base_branch_dir / "ATD_identification" / "cycle_catalog.json")
    if not catalog:
        return None

    for scc in catalog.get("sccs", []):
        for cyc in scc.get("cycles", []):
            if str(cyc.get("id")) == str(cycle_id):
                edges = cyc.get("edges") or []
                edge_tuples = []
                for e in edges:
                    src = e.get("source")
                    dst = e.get("target")
                    rel = e.get("relation")
                    if src is None or dst is None:
                        continue
                    edge_tuples.append((str(src), str(dst), str(rel or "")))
                nodes = cyc.get("nodes") or []
                return {
                    "cycle_id": str(cyc.get("id")),
                    "length": cyc.get("length"),
                    "nodes": [str(n) for n in nodes],
                    "edges": edge_tuples,
                    "scc_id": str(scc.get("id")),
                }

    return None


def cycle_still_present_in_scc_report(
    cycle_def: Optional[Dict[str, Any]],
    scc_report: Optional[Dict[str, Any]],
) -> Optional[bool]:
    if not cycle_def or not scc_report:
        return None

    needed_edges = set(cycle_def.get("edges") or [])
    if not needed_edges:
        return None

    for scc in scc_report.get("sccs", []):
        present_edges = set()
        for e in scc.get("edges", []):
            src = e.get("source")
            dst = e.get("target")
            rel = e.get("relation")
            if src is None or dst is None:
                continue
            present_edges.add((str(src), str(dst), str(rel or "")))
        if needed_edges.issubset(present_edges):
            return True

    return False


def classify_outcome(row: Dict[str, Any]) -> str:
    run_kind = str(row.get("run_kind") or "").strip().lower()

    if run_kind in {"openhands_blocked", "metrics_blocked"}:
        return "blocked"
    if run_kind == "openhands_failed":
        return "openhands_failed"
    if run_kind in {"metrics_failed", "metrics_skipped_after_commit", "metrics_missing_after_commit"}:
        return "metrics_failed"

    global_improved = row.get("global_edges_decreased")
    cycle_removed = row.get("target_cycle_removed")
    tests_ok = strict_test_counts_ok(row.get("baseline_test_counts"), row.get("test_counts"))

    structure_ok = (global_improved is True) and (cycle_removed is True)
    structure_not_ok = (global_improved is False) or (cycle_removed is False)

    if structure_ok and tests_ok:
        return "success"
    if structure_ok and not tests_ok:
        return "behavior_regressed"
    if structure_not_ok and tests_ok:
        return "structure_not_improved"
    if structure_not_ok and not tests_ok:
        return "both_failed"
    return "other_error"