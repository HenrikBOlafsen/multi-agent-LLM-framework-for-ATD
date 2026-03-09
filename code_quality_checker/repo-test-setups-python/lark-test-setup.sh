#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Lark: installing project + test deps"

  # Install project
  python -m pip install -e .

  # Upstream test deps (from tox.ini)
  if [[ -f "test-requirements.txt" ]]; then
    python -m pip install -r test-requirements.txt
  fi

  # Lark has optional deps that tests may exercise.
  # Installing them avoids “skipped because missing extra dep” surprises.
  python -m pip install -e ".[regex,nearley,atomic_cache,interegular]" || true

  # Harness pytest plugins
  python -m pip install pytest pytest-cov pytest-timeout
}

QUALITY_TEST() {
  # Lark doesn't need xdist; keep deterministic
  export USE_PYTEST_XDIST=0

  # Match upstream tox command: "python -m tests"
  # BUT your default_pytest_run already worked fine and gives coverage/junit.
  # So we keep the harness run unless you specifically want upstream parity.
  default_pytest_run
}