#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "OmegaConf: legacy editable install + generate ANTLR parsers"

  python -m pip install -U "pip<27" "setuptools<75" wheel

  export PYTHONPATH=".:${PYTHONPATH:-}"

  python -m pip install antlr4-python3-runtime PyYAML attrs || true

  if [[ -f setup.py ]]; then
    python setup.py develop || true
    python setup.py antlr || true
  fi

  python -m pip install \
    "pytest>=7.4,<8" \
    pytest-cov \
    pytest-timeout \
    pytest-mock \
    pydevd || true
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0

  # same environment prep as default_pytest_run (minimal)
  export WATCHDOG_FORCE_POLLING=1
  _pp="${PYTHONPATH:-}"
  export PYTHONPATH=".:${PYTHONPATH:-}"
  [[ -d "src" ]] && export PYTHONPATH="src:${PYTHONPATH:-}"
  for tdir in tests test t; do
    [[ -d "$tdir" ]] && export PYTHONPATH="$tdir:${PYTHONPATH:-}"
  done

  : "${PYTEST_TIMEOUT:=180}"
  : "${COV_FAIL_UNDER:=0}"
  TEST_LOG="$OUT_ABS/pytest_full.log"

  # Coverage targets (reuse your detected SRC_PATHS)
  cov_args=()
  for p in "${SRC_PATHS[@]}"; do
    cov_args+=( "--cov=$p" )
  done

  set -o pipefail
  pytest -q \
    --disable-warnings \
    --timeout="$PYTEST_TIMEOUT" --timeout-method=thread \
    --durations=25 \
    --junitxml "$OUT_ABS/pytest.xml" \
    "${cov_args[@]}" --cov-fail-under="$COV_FAIL_UNDER" \
    --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
    -W ignore:"pkg_resources is deprecated as an API":DeprecationWarning \
    -W ignore:"easy_install command is deprecated":DeprecationWarning \
    --ignore=tests/test_pydev_resolver_plugin.py \
    2>&1 | tee "$TEST_LOG" || true

  PYTEST_RC=${PIPESTATUS[0]}
  export PYTHONPATH="$_pp"
  if [[ $PYTEST_RC -ne 0 ]]; then
    echo "pytest failed with exit code $PYTEST_RC" >&2
    exit $PYTEST_RC
  fi
}

