#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Installing Rich via Poetry into .qc-venv (pytest-timeout required)"

  # Ensure Poetry installs into the active venv (.qc-venv)
  export POETRY_VIRTUALENVS_CREATE=false
  export POETRY_NO_INTERACTION=1

  python -m pip install -U poetry

  # Install project + dev deps exactly as upstream expects
  poetry install

  # Enforce pytest-timeout invariant
  python -m pip install -U pytest-timeout
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0
  default_pytest_run
}
