#!/usr/bin/env bash

QUALITY_INSTALL() {
  echo "Installing full pydantic test environment via uv"

  # Install all pydantic-defined dependency groups
  uv sync --active --all-groups

  # Enable optional runtime features exercised by tests
  pip install "pydantic[email]"

  # Harness-required pytest plugins (NOT provided by pydantic)
  pip install pytest pytest-cov pytest-timeout

  # Optional but useful
  pip install memray
}

QUALITY_TEST() {
  # pydantic tests do not behave well with xdist here
  export USE_PYTEST_XDIST=0

  # Enable memray-based tests
  export PYDANTIC_MEMRAY=1

  default_pytest_run
}
