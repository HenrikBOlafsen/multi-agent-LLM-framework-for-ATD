#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "dulwich: install base + all extras (fail if anything is missing)"

  python -m pip install -U pip wheel setuptools

  # Base
  python -m pip install -e .

  # Install extras one-by-one so you know exactly what failed
  for ex in fastimport https pgp paramiko colordiff dev merge fuzzing patiencediff aiohttp; do
    echo "dulwich: installing extra [$ex]"
    python -m pip install -e ".[${ex}]"
  done

  # Test tooling
  python -m pip install pytest pytest-cov pytest-timeout
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0
  default_pytest_run
}
