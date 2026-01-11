#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Dask: installing test env (dataframe + diagnostics + test), but NOT distributed"

  # Install editable dask + extras that don't pin distributed
  python -m pip install -e ".[array,dataframe,diagnostics,test]"

  # Ensure the key dataframe deps exist (belt & suspenders)
  python -m pip install "pyarrow>=14.0.1" "pandas>=2.0" "numpy>=1.24"

  # Harness baseline
  python -m pip install pytest pytest-cov pytest-timeout
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0
  unset PYTEST_ADDOPTS
  default_pytest_run
}
