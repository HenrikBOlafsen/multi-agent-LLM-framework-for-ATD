#!/usr/bin/env python3
"""
Simple declarative case checker for the ATD pipeline (no pytest).

Usage:
  python3 test_runs/check_case.py test_runs/cases/<case_dir>

Expects in <case_dir>:
  - pipeline.yaml
  - expected.json

Resume smoke testing helpers:
  - --write-snapshot <path>
  - --assert-resume <snapshot_path>
  - --assert-has-blocked
      Assert that at least one unit is blocked due to LLM unavailability.
  - --assert-has-midrun-edit
      Assert that at least one OpenHands run performed the "edit" tool call,
      by checking result artifacts (run.log or git_diff.patch).
  - --assert-fail-fast-phase <phase>
      Assert that fail-fast stopped iteration after the first blocked unit for that phase.

Blocked means:
  - status_<phase>.json has outcome="blocked"
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"Bad JSON {p}: {e}")


def safe_load_json(p: Path) -> Optional[Any]:
    try:
        if not p.exists() or p.stat().st_size == 0:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def mtime_or_none(p: Path) -> Optional[float]:
    try:
        return p.stat().st_mtime
    except Exception:
        return None


def read_text_safe(p: Path) -> str:
    try:
        if not p.exists() or p.stat().st_size == 0:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


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
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
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
        out.append({"repo": parts[0], "base_branch": parts[1], "entry": parts[2], "language": parts[3]})
    return out


def read_cycles(p: Path) -> List[Dict[str, str]]:
    out = []
    for ln in read_lines(p):
        parts = ln.split()
        if len(parts) < 3:
            die(f"Bad cycles file line: {ln}")
        out.append({"repo": parts[0], "base_branch": parts[1], "cycle_id": parts[2]})
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
# Status helpers
# ------------------------------------------------------------

def read_status(path: Path) -> Tuple[Optional[str], Optional[str]]:
    data = safe_load_json(path)
    if not isinstance(data, dict):
        return (None, None)
    out = data.get("outcome")
    rea = data.get("reason")
    return (str(out) if out is not None else None, str(rea) if rea is not None else None)


def norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def is_ok(outcome: Optional[str]) -> bool:
    return norm(outcome) == "ok"


def is_blocked(outcome: Optional[str]) -> bool:
    return norm(outcome) == "blocked"


def is_openhands_success(outcome: Optional[str]) -> bool:
    v = norm(outcome)
    return v in ("committed", "no_changes")


# ------------------------------------------------------------
# Snapshot / Resume helpers
# ------------------------------------------------------------

def unit_key(repo: str, base_branch: str, cycle_id: str, mode: str, branch: str) -> str:
    return f"{repo}|{base_branch}|{cycle_id}|{mode}|{branch}"


def write_snapshot(out_path: Path, cfg: Dict[str, Any], exp: Dict[str, Any]) -> None:
    results_root = Path(cfg["results_root"]).resolve()
    cycles_file = Path(cfg["cycles_file"]).resolve()
    experiment_id = str(cfg["experiment_id"])

    cycles = read_cycles(cycles_file)
    modes = exp.get("modes")
    if not isinstance(modes, list) or not modes:
        die("expected.json must contain modes: []")

    snap: Dict[str, Any] = {
        "schema": 3,
        "case_results_root": str(results_root),
        "experiment_id": experiment_id,
        "units": {},
    }

    for c in cycles:
        for mode in modes:
            branch = make_branch(experiment_id, mode, c["cycle_id"])
            base = results_root / c["repo"] / "branches" / branch

            p_explain = base / "status_explain.json"
            p_openhands = base / "status_openhands.json"
            p_oh_status = base / "openhands" / "status.json"

            ex_out, ex_reason = read_status(p_explain)
            oh_phase_out, oh_phase_reason = read_status(p_openhands)

            oh_data = safe_load_json(p_oh_status)
            oh_outcome = (
                str(oh_data.get("outcome"))
                if isinstance(oh_data, dict) and oh_data.get("outcome") is not None
                else None
            )

            snap["units"][unit_key(c["repo"], c["base_branch"], c["cycle_id"], mode, branch)] = {
                "repo": c["repo"],
                "base_branch": c["base_branch"],
                "cycle_id": c["cycle_id"],
                "mode": mode,
                "branch": branch,
                "paths": {
                    "status_explain": str(p_explain),
                    "status_openhands": str(p_openhands),
                    "openhands_status": str(p_oh_status),
                },
                "mtimes": {
                    "status_explain": mtime_or_none(p_explain),
                    "status_openhands": mtime_or_none(p_openhands),
                    "openhands_status": mtime_or_none(p_oh_status),
                },
                "status": {
                    "explain": {"outcome": ex_out, "reason": ex_reason},
                    "openhands_phase": {"outcome": oh_phase_out, "reason": oh_phase_reason},
                    "openhands": {"outcome": oh_outcome},
                },
            }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    print(f"📝 snapshot written: {out_path}")


def assert_has_blocked(case_dir: Path, cfg: Dict[str, Any], exp: Dict[str, Any]) -> None:
    results_root = Path(cfg["results_root"]).resolve()
    cycles_file = Path(cfg["cycles_file"]).resolve()
    experiment_id = str(cfg["experiment_id"])
    cycles = read_cycles(cycles_file)

    modes = exp.get("modes")
    if not isinstance(modes, list) or not modes:
        die("expected.json must contain modes: []")

    found: List[str] = []
    for c in cycles:
        for mode in modes:
            branch = make_branch(experiment_id, mode, c["cycle_id"])
            base = results_root / c["repo"] / "branches" / branch
            p_explain = base / "status_explain.json"
            p_openhands = base / "status_openhands.json"

            ex_out, ex_reason = read_status(p_explain)
            oh_out, oh_reason = read_status(p_openhands)

            if is_blocked(ex_out) or is_blocked(oh_out):
                found.append(
                    f"{c['repo']} {mode} {c['cycle_id']}: "
                    f"blocked (explain={ex_out}/{ex_reason}, openhands={oh_out}/{oh_reason})"
                )

    if not found:
        die("Expected at least one unit to be blocked (status_* outcome=blocked), but found none.")

    print("✅ found blocked unit(s):")
    for x in found:
        print(" - " + x)


def assert_has_midrun_edit(case_dir: Path, cfg: Dict[str, Any], exp: Dict[str, Any]) -> None:
    """
    Verify OpenHands got far enough to run the marker-writing tool call.
    We check result artifacts (not worktrees):
      - openhands/run.log contains marker filenames OR
      - openhands/git_diff.patch contains marker filenames
    """
    results_root = Path(cfg["results_root"]).resolve()
    cycles_file = Path(cfg["cycles_file"]).resolve()
    experiment_id = str(cfg["experiment_id"])
    cycles = read_cycles(cycles_file)

    modes = exp.get("modes")
    if not isinstance(modes, list) or not modes:
        die("expected.json must contain modes: []")

    needle1 = "_smoke_midrun_edit_marker.txt"
    needle2 = "ATD_SMOKE_EDIT.txt"

    hits: List[str] = []
    for c in cycles:
        for mode in modes:
            branch = make_branch(experiment_id, mode, c["cycle_id"])
            base = results_root / c["repo"] / "branches" / branch
            p_log = base / "openhands" / "run.log"
            p_patch = base / "openhands" / "git_diff.patch"

            log_txt = read_text_safe(p_log)
            patch_txt = read_text_safe(p_patch)

            if (needle1 in log_txt and needle2 in log_txt) or (needle1 in patch_txt and needle2 in patch_txt):
                hits.append(f"{c['repo']} {mode} {c['cycle_id']}: {p_log if p_log.exists() else p_patch}")

    if not hits:
        die(
            "Expected mid-run OpenHands edit evidence, but found none.\n"
            f"Looked for both '{needle1}' and '{needle2}' in openhands/run.log or openhands/git_diff.patch"
        )

    print("✅ found mid-run edit evidence:")
    for x in hits:
        print(" - " + x)


def assert_fail_fast_phase(case_dir: Path, cfg: Dict[str, Any], exp: Dict[str, Any], phase: str) -> None:
    """
    Fail-fast means: after the first blocked unit in a phase, the pipeline should stop
    attempting remaining units for that phase (so later units shouldn't have status_<phase>.json written).
    """
    results_root = Path(cfg["results_root"]).resolve()
    cycles_file = Path(cfg["cycles_file"]).resolve()
    experiment_id = str(cfg["experiment_id"])
    cycles = read_cycles(cycles_file)

    modes = exp.get("modes")
    if not isinstance(modes, list) or not modes:
        die("expected.json must contain modes: []")

    status_name = f"status_{phase}.json"
    statuses: List[Tuple[int, str, Path, Optional[str], Optional[str]]] = []

    idx = 0
    for c in cycles:
        for mode in modes:
            branch = make_branch(experiment_id, mode, c["cycle_id"])
            base = results_root / c["repo"] / "branches" / branch
            p = base / status_name
            out, rea = read_status(p)
            statuses.append((idx, f"{c['repo']} {mode} {c['cycle_id']}", p, out, rea))
            idx += 1

    first_blocked_idx: Optional[int] = None
    first_blocked_label: Optional[str] = None

    for i, label, p, out, rea in statuses:
        if is_blocked(out):
            first_blocked_idx = i
            first_blocked_label = f"{label} ({out}/{rea})"
            break

    if first_blocked_idx is None:
        die(f"Expected at least one blocked unit for phase={phase}, but found none.")

    # After first blocked, later statuses should NOT exist (or be empty)
    bad: List[str] = []
    for i, label, p, out, rea in statuses:
        if i <= first_blocked_idx:
            continue
        if p.exists() and p.stat().st_size > 0:
            # If the pipeline proceeded, we'd see outcome values
            bad.append(f"unit index {i} has {status_name} written: {label} ({out}/{rea}) at {p}")

    if bad:
        die(
            f"Fail-fast assertion failed for phase={phase}.\n"
            f"First blocked at index={first_blocked_idx}: {first_blocked_label}\n"
            "But later units still wrote status files:\n" + "\n".join(" - " + x for x in bad)
        )

    print(f"✅ fail-fast OK for phase={phase} (first blocked index={first_blocked_idx})")


def assert_resume(snapshot_path: Path, cfg: Dict[str, Any], exp: Dict[str, Any]) -> None:
    snap = load_json(snapshot_path)
    if not isinstance(snap, dict) or snap.get("schema") not in (3,):
        die(f"Bad snapshot schema in {snapshot_path}")

    units = snap.get("units")
    if not isinstance(units, dict):
        die(f"Bad snapshot: units missing in {snapshot_path}")

    results_root = Path(cfg["results_root"]).resolve()
    bad: List[str] = []

    for k, u in units.items():
        if not isinstance(u, dict):
            continue

        p_explain = Path(u["paths"]["status_explain"])
        p_openhands = Path(u["paths"]["status_openhands"])
        p_oh_status = Path(u["paths"]["openhands_status"])

        # Safety: snapshot paths must be under results_root
        for p in (p_explain, p_openhands, p_oh_status):
            try:
                rp = p.resolve()
                if str(results_root) not in str(rp):
                    bad.append(f"{k}: snapshot path not under results_root: {rp}")
            except Exception:
                pass

        # Snapshot state
        s_ex_out = u["status"]["explain"]["outcome"]
        s_oh_phase_out = u["status"]["openhands_phase"]["outcome"]
        s_oh_outcome = u["status"]["openhands"].get("outcome")

        s_m_ex = u["mtimes"]["status_explain"]
        s_m_ohp = u["mtimes"]["status_openhands"]
        s_m_ohs = u["mtimes"]["openhands_status"]

        snapshot_completed = is_ok(s_oh_phase_out) and is_openhands_success(s_oh_outcome)

        snapshot_needs_rerun = (
            not snapshot_completed
            or s_m_ex is None
            or s_m_ohp is None
            or s_m_ohs is None
            or is_blocked(s_ex_out)
            or is_blocked(s_oh_phase_out)
        )

        # Current state
        c_ex_out, c_ex_reason = read_status(p_explain)
        c_oh_phase_out, c_oh_phase_reason = read_status(p_openhands)

        c_oh_data = safe_load_json(p_oh_status)
        c_oh_outcome = (
            str(c_oh_data.get("outcome"))
            if isinstance(c_oh_data, dict) and c_oh_data.get("outcome") is not None
            else None
        )

        c_m_ex = mtime_or_none(p_explain)
        c_m_ohp = mtime_or_none(p_openhands)
        c_m_ohs = mtime_or_none(p_oh_status)

        current_completed = is_ok(c_oh_phase_out) and is_openhands_success(c_oh_outcome)

        if snapshot_completed:
            # Completed units must not be touched by resume run.
            if s_m_ex is not None and c_m_ex is not None and c_m_ex != s_m_ex:
                bad.append(f"{k}: was completed but status_explain.json changed (mtime differs)")
            if s_m_ohp is not None and c_m_ohp is not None and c_m_ohp != s_m_ohp:
                bad.append(f"{k}: was completed but status_openhands.json changed (mtime differs)")
            if s_m_ohs is not None and c_m_ohs is not None and c_m_ohs != s_m_ohs:
                bad.append(f"{k}: was completed but openhands/status.json changed (mtime differs)")
            continue

        if snapshot_needs_rerun:
            if not current_completed:
                bad.append(
                    f"{k}: was incomplete/blocked in snapshot but is still not completed now "
                    f"(now: explain={c_ex_out}/{c_ex_reason}, openhands_phase={c_oh_phase_out}/{c_oh_phase_reason}, openhands={c_oh_outcome})"
                )

            # Ensure something changed in core files (proof of rerun)
            changed = False
            for (s_m, c_m) in ((s_m_ex, c_m_ex), (s_m_ohp, c_m_ohp), (s_m_ohs, c_m_ohs)):
                if s_m is None and c_m is not None:
                    changed = True
                elif s_m is not None and c_m is not None and c_m != s_m:
                    changed = True

            if not changed:
                bad.append(f"{k}: expected rerun but no core mtimes changed")
            continue

        # Defensive: if snapshot wasn't completed and wasn't marked for rerun, still require completion.
        if not current_completed:
            bad.append(f"{k}: not completed after resume (unexpected state)")

    if bad:
        die("Resume assertions failed:\n" + "\n".join(" - " + x for x in bad))

    print(f"✅ resume OK (snapshot: {snapshot_path})")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_dir")
    ap.add_argument("--write-snapshot", dest="write_snapshot", default=None)
    ap.add_argument("--assert-resume", dest="assert_resume", default=None)
    ap.add_argument("--assert-has-blocked", dest="assert_has_blocked", action="store_true")
    ap.add_argument("--assert-has-midrun-edit", dest="assert_has_midrun_edit", action="store_true")
    ap.add_argument("--assert-fail-fast-phase", dest="assert_fail_fast_phase", default=None)
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

    if args.assert_has_blocked:
        assert_has_blocked(case_dir, cfg, exp)
        return

    if args.assert_has_midrun_edit:
        assert_has_midrun_edit(case_dir, cfg, exp)
        return

    if args.assert_fail_fast_phase:
        assert_fail_fast_phase(case_dir, cfg, exp, args.assert_fail_fast_phase.strip())
        return

    if args.write_snapshot:
        write_snapshot(Path(args.write_snapshot), cfg, exp)
        return

    if args.assert_resume:
        assert_resume(Path(args.assert_resume), cfg, exp)
        return

    # --------------------------------------------------------
    # Strict checks (original behavior)
    # --------------------------------------------------------
    projects_dir = Path(cfg["projects_dir"]).resolve()
    results_root = Path(cfg["results_root"]).resolve()
    repos_file = Path(cfg["repos_file"]).resolve()
    cycles_file = Path(cfg["cycles_file"]).resolve()
    experiment_id = str(cfg["experiment_id"])

    if not experiment_id:
        die("experiment_id missing")

    repos = read_repos(repos_file)
    cycles = read_cycles(cycles_file)

    modes = exp.get("modes")
    if not isinstance(modes, list) or not modes:
        die("expected.json must contain modes: []")

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

    llm = exp.get("llm") or {}
    branch_expect = llm.get("git_branch_exists", None)
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

                if branch_expect is not None:
                    repo_dir = projects_dir / c["repo"]
                    exists = git_branch_exists(repo_dir, branch)
                    if bool(branch_expect) != bool(exists):
                        want = "exist" if branch_expect else "not exist"
                        die(f"Branch check failed: expected {branch} to {want} in {repo_dir}")

        print("✅ llm OK")

    metrics = exp.get("metrics") or {}
    if metrics:
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

                apply_block(metrics, ctx, f"metrics {c['repo']} {mode}")

                oh_path = Path(fmt("{results_root}/{repo}/branches/{branch}/openhands/status.json", ctx))
                must_nonempty(str(oh_path), "openhands status.json")
                oh = load_json(oh_path)
                oh_out = str(oh.get("outcome", "")).strip()

                ms_path = Path(fmt("{results_root}/{repo}/branches/{branch}/status_metrics.json", ctx))
                must_nonempty(str(ms_path), "metrics status")
                ms = load_json(ms_path)
                got = str(ms.get("outcome", "")).strip()

                expected = "ok" if oh_out == "committed" else "skipped"
                if got != expected:
                    die(f"metrics {c['repo']} {mode}: expected {expected}, got {got} (openhands={oh_out})")

        print("✅ metrics OK")

    print(f"\n🎉 Case passed: {case_dir}")


if __name__ == "__main__":
    main()
