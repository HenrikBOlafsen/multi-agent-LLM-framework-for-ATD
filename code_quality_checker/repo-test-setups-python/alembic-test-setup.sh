#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  python -m pip install -e .
  python -m pip install \
    "pytest>8,<8.4" \
    pytest-cov \
    pytest-timeout \
    "black==25.1.0" \
    zimports \
    tzdata \
    junitparser
}

QUALITY_TEST() {
  default_pytest_run
}