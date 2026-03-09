#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Kombu: installing tox(unit)-aligned deps into active .qc-venv"

  export PIP_EXTRA_INDEX_URL="https://celery.github.io/celery-wheelhouse/repo/simple/"

  python -m pip install -e .

  python -m pip install -r requirements/dev.txt
  python -m pip install -r requirements/default.txt
  python -m pip install -r requirements/test.txt

  # IMPORTANT: this one pulls in boto3/azure/google extras via -r extras/*.txt
  python -m pip install -r requirements/test-ci.txt

  python -m pip install pytest pytest-cov pytest-timeout
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0
  default_pytest_run
}
