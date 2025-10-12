#!/usr/bin/env bash
# Run analyzers in the prepared worktree, fail-fast on *tooling*, not on findings.
# Usage:
#   ./quality_checker_run_tools.sh <WT_ROOT> <OUT_ABS>
#
# Env knobs (optional):
#   QUALITY_TIMEOUT_SECONDS   default: 20
#   QUALITY_TIMEOUT_METHOD    default: signal   (signal | thread)
#   QUALITY_MAXFAIL           default: 0        (0 means don't stop early)
#   QUALITY_PYTEST_ARGS       default: ""       (extra args, e.g. -k 'not slow')

set -euo pipefail
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TZ=UTC
export PYTHONHASHSEED=0
export WATCHDOG_FORCE_POLLING="${WATCHDOG_FORCE_POLLING:-1}"

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <WT_ROOT> <OUT_ABS>" >&2
  exit 2
fi

WT_ROOT="$1"
OUT_ABS="$2"

# --- Read explicit source paths (required) -----------------------------------
mapfile -t SRC_PATHS < "$OUT_ABS/src_paths.txt"
if [[ ${#SRC_PATHS[@]} -eq 0 ]]; then
  echo "Error: empty src_paths.txt; you must provide source paths explicitly." >&2
  exit 3
fi

# --- Use per-ref/shared venv if present --------------------------------------
PYTEST_PY="$(cat "$OUT_ABS/pytest_python.txt" 2>/dev/null || true)"
if [[ -n "$PYTEST_PY" ]]; then
  export PATH="$(dirname "$PYTEST_PY"):$PATH"
fi

# --- Require core tools on PATH (installed by prepare_env) -------------------
for t in ruff mypy radon vulture bandit pip-audit analyze_code_quality; do
  if ! command -v "$t" >/dev/null 2>&1; then
    echo "Error: required tool '$t' not on PATH." >&2
    exit 1
  fi
done

# --- Compose common target args ----------------------------------------------
coverage_args=(); radon_targets=(); vulture_targets=(); bandit_targets=(); mypy_targets=()
for p in "${SRC_PATHS[@]}"; do
  coverage_args+=( "--cov=$p" )
  radon_targets+=( "$p" )
  vulture_targets+=( "$p" )
  bandit_targets+=( "$p" )
  mypy_targets+=( "$p" )
done

# --- Tunables ----------------------------------------------------------------
QUALITY_TIMEOUT_SECONDS="${QUALITY_TIMEOUT_SECONDS:-20}"
QUALITY_TIMEOUT_METHOD="${QUALITY_TIMEOUT_METHOD:-signal}"   # signal|thread
QUALITY_MAXFAIL="${QUALITY_MAXFAIL:-0}"
QUALITY_PYTEST_ARGS="${QUALITY_PYTEST_ARGS:-}"

(
  cd "$WT_ROOT"

  # =========================
  # 1) TESTS + COVERAGE
  # =========================
  if [[ -n "$PYTEST_PY" ]]; then
    "$PYTEST_PY" - <<'PY'
import sys, importlib
for mod in ("pytest", "pytest_timeout", "pytest_cov"):
    try:
        importlib.import_module(mod)
    except Exception as e:
        print(f"Error: required pytest plugin missing in per-ref venv: {mod}: {e}", file=sys.stderr)
        sys.exit(1)
PY
    _prev_pp="${PYTHONPATH:-}"
    [[ -d "src" ]] && export PYTHONPATH="src:${PYTHONPATH:-}"
    test_target="."; [[ -d "tests" ]] && test_target="tests"

    set +e
    # shellcheck disable=SC2086
    "$PYTEST_PY" -m pytest -q \
      --maxfail="${QUALITY_MAXFAIL}" --disable-warnings \
      --timeout="${QUALITY_TIMEOUT_SECONDS}" --timeout-method="${QUALITY_TIMEOUT_METHOD}" \
      --durations=25 \
      --junitxml "$OUT_ABS/pytest.xml" \
      "${coverage_args[@]}" \
      --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
      $QUALITY_PYTEST_ARGS \
      "$test_target" \
      >"$OUT_ABS/pytest.out.txt" 2>&1
    PYTEST_STATUS=$?
    set -e
    echo "${PYTEST_STATUS:-99}" > "$OUT_ABS/pytest_status.txt"

    export PYTHONPATH="$_prev_pp"
  else
    command -v pytest >/dev/null 2>&1 || { echo "Error: no per-ref pytest and no global pytest."; exit 1; }
    python -c "import pytest, pytest_timeout, pytest_cov" >/dev/null 2>&1 || {
      echo "Error: global pytest missing required plugins (pytest-timeout, pytest-cov)."; exit 1; }
    _prev_pp="${PYTHONPATH:-}"
    [[ -d "src" ]] && export PYTHONPATH="src:${PYTHONPATH:-}"
    test_target="."; [[ -d "tests" ]] && test_target="tests"

    set +e
    # shellcheck disable=SC2086
    pytest -q \
      --maxfail="${QUALITY_MAXFAIL}" --disable-warnings \
      --timeout="${QUALITY_TIMEOUT_SECONDS}" --timeout-method="${QUALITY_TIMEOUT_METHOD}" \
      --durations=25 \
      --junitxml "$OUT_ABS/pytest.xml" \
      "${coverage_args[@]}" \
      --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
      $QUALITY_PYTEST_ARGS \
      "$test_target" \
      >"$OUT_ABS/pytest.out.txt" 2>&1
    PYTEST_STATUS=$?
    set -e
    echo "${PYTEST_STATUS:-99}" > "$OUT_ABS/pytest_status.txt"

    export PYTHONPATH="$_prev_pp"
  fi

  [[ -s "$OUT_ABS/pytest.xml"   ]] || { echo "Error: missing pytest.xml"; exit 1; }
  [[ -s "$OUT_ABS/coverage.xml" ]] || { echo "Error: missing coverage.xml"; exit 1; }

  # =========================
  # 2) RUFF
  # =========================
  set +e
  ruff check --select ALL --ignore D203,D213 --output-format=json \
    "${SRC_PATHS[@]}" \
    >"$OUT_ABS/ruff.json" 2>&1
  RUFF_STATUS=$?
  set -e
  echo "${RUFF_STATUS:-99}" > "$OUT_ABS/ruff_status.txt"
  [[ -s "$OUT_ABS/ruff.json" ]] || { echo "Error: missing ruff.json"; exit 1; }

  # =========================
  # 3) MYPY
  # =========================
  set +e
  mypy --hide-error-context --no-error-summary "${mypy_targets[@]}" \
    >"$OUT_ABS/mypy.txt" 2>&1
  MYPY_STATUS=$?
  set -e
  echo "${MYPY_STATUS:-99}" > "$OUT_ABS/mypy_status.txt"
  # If mypy produced no output (clean run with suppressed summary), add a success marker
  if [[ ! -s "$OUT_ABS/mypy.txt" ]]; then
    echo "Success: mypy found no issues." > "$OUT_ABS/mypy.txt"
  fi

  # =========================
  # 4) RADON
  # =========================
  radon cc -j "${radon_targets[@]}" > "$OUT_ABS/radon_cc.json"
  radon mi -j "${radon_targets[@]}" > "$OUT_ABS/radon_mi.json"
  [[ -s "$OUT_ABS/radon_cc.json" ]] || { echo "Error: missing radon_cc.json"; exit 1; }
  [[ -s "$OUT_ABS/radon_mi.json" ]] || { echo "Error: missing radon_mi.json"; exit 1; }

  # =========================
  # 5) VULTURE
  # =========================
  vulture "${vulture_targets[@]}" > "$OUT_ABS/vulture.txt"
  [[ -e "$OUT_ABS/vulture.txt" ]] || { echo "Error: missing vulture.txt"; exit 1; }

  # =========================
  # 6) BANDIT
  # =========================
  set +e
  bandit -q -r "${bandit_targets[@]}" -f json -o "$OUT_ABS/bandit.json"
  BANDIT_STATUS=$?
  set -e
  echo "${BANDIT_STATUS:-99}" > "$OUT_ABS/bandit_status.txt"
  [[ -s "$OUT_ABS/bandit.json" ]] || { echo "Error: missing bandit.json"; exit 1; }

  # =========================
  # 7) PIP-AUDIT
  # =========================
  set +e
  pip-audit -f json -o "$OUT_ABS/pip_audit.json"
  PIPAUDIT_STATUS=$?
  set -e
  echo "${PIPAUDIT_STATUS:-99}" > "$OUT_ABS/pip_audit_status.txt"
  [[ -s "$OUT_ABS/pip_audit.json" ]] || { echo "Error: missing pip_audit.json"; exit 1; }

  # =========================
  # 8) PYEXAMINE (project-specific)
  # =========================
  analyze_code_quality "$WT_ROOT" --output "$OUT_ABS/pyexamine.csv"
  [[ -s "$OUT_ABS/pyexamine.csv" ]] || { echo "Error: missing pyexamine.csv"; exit 1; }
)

echo "==> Collected metrics in $OUT_ABS"
