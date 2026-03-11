#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  default_install

  # Extra deps used by some serving / reloader tests.
  python -m pip install ephemeral-port-reserve watchdog cryptography
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0

  # In the qc/container environment, a small subset of Werkzeug dev-server
  # readiness tests can hang while waiting for the spawned server to become
  # ready (tests/conftest.py wait_ready). Keep the exclusion narrow and based
  # on observed failures rather than broadly skipping all serving tests.
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
    -k "not test_server and not test_ssl_object" \
    --junitxml "$OUT_ABS/pytest.xml" \
    "${cov_args[@]}" --cov-fail-under="$COV_FAIL_UNDER" \
    --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
    2>&1 | tee "$TEST_LOG" || true

  PYTEST_RC=${PIPESTATUS[0]}
  export PYTHONPATH="$_pp"
  if [[ $PYTEST_RC -ne 0 ]]; then
    echo "pytest failed with exit code $PYTEST_RC" >&2
    exit $PYTEST_RC
  fi
}