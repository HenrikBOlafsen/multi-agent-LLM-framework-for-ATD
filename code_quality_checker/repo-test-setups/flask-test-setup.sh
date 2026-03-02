#!/usr/bin/env bash
# repo-test-setups/flask-test-setup.sh
#
# Minimal, "honest" Flask run:
# - install Flask editable with async extra so async-view tests can run
# - install pytest tooling (because we override QUALITY_TEST)
# - run pytest normally

set -euo pipefail

QUALITY_INSTALL() {
  echo "Flask: install editable with async extra + test runner deps"
  python -m pip install -e ".[async]"
  python -m pip install pytest pytest-cov pytest-timeout
}

QUALITY_TEST() {
  echo "Flask: running pytest"
  export WATCHDOG_FORCE_POLLING=1
  python -m pytest -q
}