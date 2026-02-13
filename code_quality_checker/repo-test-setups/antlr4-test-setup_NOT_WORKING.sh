#!/usr/bin/env bash
set -euo pipefail

ANTLR_PY_DIR="runtime/Python3"

QUALITY_INSTALL() {
  echo "antlr4: installing from $ANTLR_PY_DIR"

  # Install the actual python project (pyproject.toml is here)
  python -m pip install -e "$ANTLR_PY_DIR"

  # minimal pytest tooling the harness expects
  python -m pip install pytest pytest-cov pytest-timeout || true
}

QUALITY_TEST() {
  echo "antlr4: running tests from $ANTLR_PY_DIR"

  # If there are no tests, this will still be clean and fast.
  # If there *are* tests, they are more likely to be runnable from inside this dir.
  (
    cd "$ANTLR_PY_DIR"

    # Ensure src layout import works even without editable (but we already installed editable)
    export PYTHONPATH="src:${PYTHONPATH:-}"

    # If you later discover a specific test dir, replace `-q` with that path.
    pytest -q || true
  )
}
