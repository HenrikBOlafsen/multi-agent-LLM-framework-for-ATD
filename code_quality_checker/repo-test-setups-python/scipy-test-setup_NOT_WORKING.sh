#!/usr/bin/env bash
# repo-test-setups/scipy-test-setup.sh
#
# Minimal, close-to-normal SciPy run:
# - ensure required git submodules are present (SciPy requires this)
# - install build+test requirements
# - build/install SciPy editable (meson-python)
# - run pytest

set -euo pipefail

QUALITY_INSTALL() {
  echo "SciPy: preparing source tree"

  # SciPy uses git submodules (error shows `xsf` missing).
  if command -v git >/dev/null 2>&1 && [[ -f .gitmodules ]]; then
    git submodule update --init --recursive
  fi

  echo "SciPy: checking toolchain"
  if ! command -v gfortran >/dev/null 2>&1; then
    echo "ERROR: SciPy build needs a Fortran compiler (gfortran not found)." >&2
    exit 2
  fi

  echo "SciPy: installing build requirements"
  if [[ -f requirements/build.txt ]]; then
    python -m pip install -r requirements/build.txt
  else
    python -m pip install "numpy>=1.26.4" "meson-python>=0.15.0" "Cython>=3.0.8" \
      "pybind11>=2.13.2" "pythran>=0.14.0" meson ninja
  fi

  echo "SciPy: installing test requirements"
  if [[ -f requirements/test.txt ]]; then
    python -m pip install -r requirements/test.txt
  else
    python -m pip install "pytest>=8" pytest-cov pytest-timeout hypothesis threadpoolctl pooch
  fi

  echo "SciPy: editable install (no build isolation)"
  python -m pip install -e . --no-build-isolation

  python - <<'PY'
import numpy, scipy
print("numpy:", numpy.__version__)
print("scipy:", scipy.__version__)
PY
}

QUALITY_TEST() {
  echo "SciPy: running pytest"
  export WATCHDOG_FORCE_POLLING=1

  TEST_LOG="$OUT_ABS/pytest_full.log"
  : "${PYTEST_TIMEOUT:=180}"

  set -o pipefail
  python -m pytest -q \
    --disable-warnings \
    --timeout="$PYTEST_TIMEOUT" --timeout-method=thread \
    --durations=25 \
    --junitxml "$OUT_ABS/pytest.xml" \
    2>&1 | tee "$TEST_LOG"
}