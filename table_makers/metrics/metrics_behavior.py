from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.io_utils import path_exists, read_json


def parse_test_counts(metrics: Dict[str, Any]) -> Optional[Dict[str, int]]:
    pytest_block = metrics.get("pytest")
    if isinstance(pytest_block, dict):
        tests = int(pytest_block.get("tests", 0) or 0)
        failures = int(pytest_block.get("failures", 0) or 0)
        errors = int(pytest_block.get("errors", 0) or 0)
        skipped = int(pytest_block.get("skipped", 0) or 0)
        passed = tests - failures - errors - skipped
        return {
            "tests": tests,
            "passed": max(0, passed),
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
        }

    dotnet_block = metrics.get("dotnet_test")
    if isinstance(dotnet_block, dict):
        tests = int(dotnet_block.get("tests", 0) or 0)
        failures = int(dotnet_block.get("failures", 0) or 0)
        errors = int(dotnet_block.get("errors", 0) or 0)
        skipped = int(dotnet_block.get("skipped", 0) or 0)
        passed = tests - failures - errors - skipped
        return {
            "tests": tests,
            "passed": max(0, passed),
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
        }

    return None


def read_test_counts(metrics_path: Path) -> Optional[Dict[str, int]]:
    if not path_exists(metrics_path):
        return None
    return parse_test_counts(read_json(metrics_path))


def behavior_preserved_from_metrics(
    baseline_metrics_path: Path,
    post_metrics_path: Path,
) -> bool:
    baseline = read_test_counts(baseline_metrics_path)
    post = read_test_counts(post_metrics_path)

    if baseline is None or post is None:
        return False

    return (
        post["failures"] <= baseline["failures"]
        and post["errors"] <= baseline["errors"]
        and post["skipped"] <= baseline["skipped"]
        and post["passed"] >= baseline["passed"]
    )