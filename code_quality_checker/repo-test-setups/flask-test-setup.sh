#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Flask: install editable with async extra + test runner deps"
  python -m pip install -e ".[async]"
  python -m pip install pytest pytest-cov pytest-timeout
}

QUALITY_TEST() {
  echo "Flask: running pytest"
  default_pytest_run
}