#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "OmegaConf: legacy install path with ANTLR generation"

  # OmegaConf relies on older setuptools/setup.py flows.
  python -m pip install -U "pip<27" "setuptools<75" wheel

  export PYTHONPATH=".:${PYTHONPATH:-}"

  # Parser/runtime deps used by OmegaConf.
  python -m pip install antlr4-python3-runtime PyYAML attrs

  # Older OmegaConf versions expect setup.py-based workflows and ANTLR generation.
  if [[ -f setup.py ]]; then
    python setup.py develop
    python setup.py antlr
  fi

  python -m pip install \
    "pytest>=7.4,<8" \
    pytest-cov \
    pytest-timeout \
    pytest-mock \
    pydevd
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0

  # Keep the shared harness behavior, but add only the narrow warning filters
  # needed for OmegaConf's legacy setuptools/build_helpers collection path.
  export WATCHDOG_FORCE_POLLING=1

  _pp="${PYTHONPATH:-}"
  export PYTHONPATH=".:${PYTHONPATH:-}"
  [[ -d "src" ]] && export PYTHONPATH="src:${PYTHONPATH:-}"
  for tdir in tests test t; do
    [[ -d "$tdir" ]] && export PYTHONPATH="$tdir:${PYTHONPATH:-}"
  done

  : "${PYTEST_TIMEOUT:=180}"
  : "${COV_FAIL_UNDER:=0}"
  : "${PYTEST_WALLTIME:=}"

  TEST_LOG="$OUT_ABS/pytest_full.log"

  cov_args=()
  for p in "${SRC_PATHS[@]}"; do
    cov_args+=( "--cov=$p" )
  done

  wrap_pytest() {
    if [[ -n "${PYTEST_WALLTIME}" ]]; then
      timeout -k 30s "$PYTEST_WALLTIME" "$@"
    else
      "$@"
    fi
  }

  echo "Time for pytest"
  set -o pipefail

  wrap_pytest pytest -q \
    --disable-warnings \
    --timeout="$PYTEST_TIMEOUT" --timeout-method=thread \
    --durations=25 \
    --junitxml "$OUT_ABS/pytest.xml" \
    "${cov_args[@]}" --cov-fail-under="$COV_FAIL_UNDER" \
    --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
    -W "ignore:pkg_resources is deprecated as an API:DeprecationWarning" \
    -W "ignore:easy_install command is deprecated:DeprecationWarning" \
    2>&1 | tee "$TEST_LOG" || true

  PYTEST_RC=${PIPESTATUS[0]}
  export PYTHONPATH="$_pp"
  if [[ $PYTEST_RC -ne 0 ]]; then
    echo "pytest failed with exit code $PYTEST_RC" >&2
    exit $PYTEST_RC
  fi
}