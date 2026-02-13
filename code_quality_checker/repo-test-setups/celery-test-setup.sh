#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Celery: installing unit-only deps (no native extras)"

  export PIP_EXTRA_INDEX_URL="https://celery.github.io/celery-wheelhouse/repo/simple/"

  python -m pip install -e .

  # Core unit deps from tox.ini
  python -m pip install -r requirements/test.txt
  python -m pip install -r requirements/pkgutils.txt

  # Skip docs + CI-default bundles for now (they tend to pull native libs)
  # python -m pip install -r requirements/docs.txt || true
  # python -m pip install -r requirements/test-ci-default.txt || true

  python -m pip install pytest pytest-cov pytest-timeout
}

QUALITY_TEST() {
  echo "Celery: running unit tests only"
  export USE_PYTEST_XDIST=0

  export BOTO_CONFIG=/dev/null
  export WORKER_LOGLEVEL=INFO
  export PYTHONIOENCODING=UTF-8
  export PYTHONUNBUFFERED=1
  export PYTHONDONTWRITEBYTECODE=1

  # Force Celery unit tests path
  export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} t/unit -o junit_family=legacy"

  default_pytest_run
}
