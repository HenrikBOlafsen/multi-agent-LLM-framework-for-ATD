#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  default_install
  python -m pip install ephemeral-port-reserve watchdog || true
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0
  # Run pytest but skip the flaky dev-server test(s)
  PYTEST_EXPR="not test_server and not serving"
  pytest -q \
    --disable-warnings \
    --timeout="${PYTEST_TIMEOUT:-180}" --timeout-method=thread \
    --durations=25 \
    -k "$PYTEST_EXPR" \
    --junitxml "$OUT_ABS/pytest.xml" \
    $(for p in "${SRC_PATHS[@]}"; do printf -- "--cov=%q " "$p"; done) \
    --cov-fail-under="${COV_FAIL_UNDER:-0}" \
    --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term
}
