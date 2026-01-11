#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "OmegaConf: install project + pinned test deps"

  python -m pip install -U pip wheel setuptools

  python -m pip install -e . || true

  # Test deps
  python -m pip install \
    "attrs>=20" \
    "pytest>=7.4,<8" \
    pytest-cov \
    pytest-timeout \
    pytest-mock \
    antlr4-python3-runtime \
    PyYAML || true
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0
  # keep ignoring these (unless you want to install pydevd + friends)
  export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} --ignore=build_helpers --ignore=tests/test_pydev_resolver_plugin.py"
  default_pytest_run
}
