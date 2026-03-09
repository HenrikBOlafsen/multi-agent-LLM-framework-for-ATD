#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Kivy: building Cython extensions in-place"

  # Build requirements for Kivy
  python -m pip install -U pip wheel setuptools
  python -m pip install "cython<=3.2.0"

  # Install Kivy editable (this alone won't compile extensions)
  python -m pip install -e .

  # Compile extensions in-place
  # This is the key step that produces kivy/_clock*.so etc.
  python setup.py build_ext --inplace || {
    echo "Kivy build_ext failed (likely missing system libs like SDL/OpenGL headers)." >&2
    return 1
  }
}

QUALITY_TEST() {
  echo "Kivy: running pytest"

  export USE_PYTEST_XDIST=0

  # IMPORTANT: Kivy configures a coverage plugin that imports kivy early and crashes
  # before extensions exist. Easiest: disable coverage for pytest run.
  #
  # So: override the harness's default coverage args by clearing them.
  # If your harness *always* adds --cov, then do this:
  export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -p no:pytest_cov"

  # Also disable benchmark opts if not installed (Kivy addopts include benchmark flags)
  python -c "import pytest_benchmark" >/dev/null 2>&1 || {
    python -m pip install pytest-benchmark >/dev/null 2>&1 || true
  }

  default_pytest_run
}
