#!/usr/bin/env bash
# quality_collect.sh
#
# Simplified Python collector (keeps PyExamine + radon/vulture/bandit).
# Main simplifications vs your previous version:
# - Much simpler default_install(): try a small set of common install patterns only
#   (still allows per-repo QUALITY_INSTALL overrides).
# - Remove pytest-benchmark auto-detection and xdist support (keep plain pytest).
# - Keep venv isolation, source detection, PYTHONPATH setup, coverage+junit outputs.
#
# Usage:
#   ./quality_collect.sh <REPO_PATH> [LABEL] [SRC_HINT]
#
# Writes to: OUT_DIR if set, else .quality/<repo>/<label>
set -euo pipefail

export PYTHONHASHSEED=0
export TZ=UTC

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <REPO_PATH> [LABEL] [SRC_HINT]" >&2
  exit 2
fi

REPO_PATH="$(realpath "$1")"
REPO_NAME="$(basename "$REPO_PATH")"
LABEL="${2:-current}"
SRC_HINT="${3:-}"

# --- Git worktree (isolated checkout) ----------------------------------------
IS_GIT=0
if git -C "$REPO_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IS_GIT=1
  LABEL="${2:-$(git -C "$REPO_PATH" branch --show-current 2>/dev/null || echo current)}"
fi

OUT_ROOT="${OUT_ROOT:-.quality}"
FINAL_OUT_DIR="${OUT_DIR:-$OUT_ROOT/$REPO_NAME/$LABEL}"
mkdir -p "$FINAL_OUT_DIR"
OUT_ABS="$(realpath "$FINAL_OUT_DIR")"
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$OUT_ABS/run_started_utc.txt" || true

WT_DIR=""
WT_ROOT="$REPO_PATH"
if [[ $IS_GIT -eq 1 ]]; then
  # Offline-by-default: only fetch if explicitly allowed.
  if [[ "${QC_ALLOW_FETCH:-0}" == "1" ]]; then
    git -C "$REPO_PATH" fetch --all --quiet || true
  fi

  if ! git -C "$REPO_PATH" rev-parse --verify --quiet "${LABEL}^{commit}" >/dev/null; then
    echo "Ref '$LABEL' not found in $REPO_PATH" >&2
    exit 1
  fi

  shortsha="$(git -C "$REPO_PATH" rev-parse --short "${LABEL}^{commit}" 2>/dev/null || echo ???)"
  echo "Preparing worktree (detached HEAD $shortsha)"
  WT_DIR="$(mktemp -d -t qcwt.XXXXXX)"
  git -C "$REPO_PATH" worktree add --detach "$WT_DIR" "$LABEL" >/dev/null
  WT_ROOT="$WT_DIR"

  cleanup() {
    git -C "$REPO_PATH" worktree remove --force "$WT_DIR" 2>/dev/null || true
    rm -rf "$WT_DIR" 2>/dev/null || true
  }
  trap cleanup EXIT
fi

# --- Source detection ---------------------------------------------------------
detect_src_paths() {
  local root="$1"; local hint="${2:-}"
  local -a found=()

  if [[ -n "$hint" && -d "$root/$hint" ]]; then
    found+=("$hint")
  fi

  if [[ -d "$root/src" ]]; then
    while IFS= read -r -d '' pkg; do
      found+=("src/$(basename "$pkg")")
    done < <(find "$root/src" -mindepth 1 -maxdepth 1 -type d -exec test -e '{}/__init__.py' \; -print0)
  fi

  while IFS= read -r -d '' pkg; do
    base="$(basename "$pkg")"
    [[ "$base" =~ ^(\.|_|\-)?(venv|\.venv|build|dist|tests?)$ ]] && continue
    found+=("$base")
  done < <(find "$root" -mindepth 1 -maxdepth 1 -type d -exec test -e '{}/__init__.py' \; -print0)

  # de-dupe preserving order
  awk '!seen[$0]++{print}' < <(printf '%s\n' "${found[@]}")
}

mapfile -t SRC_PATHS < <(detect_src_paths "$WT_ROOT" "$SRC_HINT")
[[ ${#SRC_PATHS[@]} -eq 0 ]] && SRC_PATHS=(".")

printf '%s\n' "${SRC_PATHS[@]}" > "$OUT_ABS/src_paths.txt"

if [[ $IS_GIT -eq 1 ]]; then
  git -C "$WT_ROOT" rev-parse --short HEAD > "$OUT_ABS/git_sha.txt" || true
  git -C "$WT_ROOT" branch --show-current  > "$OUT_ABS/git_branch.txt" || true
fi

echo "Repo: $REPO_PATH"
echo "Worktree: $WT_ROOT  Label: $LABEL"
echo -n "Sources: "; printf '%s ' "${SRC_PATHS[@]}"; echo
echo "Out: $OUT_ABS"

# --- Per-repo setup discovery (external folder, not inside repo) --------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SETUP_DIR="${REPO_SETUP_DIR:-$SCRIPT_DIR/repo-test-setups}"
REPO_SETUP_FILE="$REPO_SETUP_DIR/${REPO_NAME}-test-setup.sh"

source "${SCRIPT_DIR}/../timing.sh"
export TIMING_PHASE="quality_collect"
export TIMING_REPO="$REPO_NAME"
export TIMING_BRANCH="$LABEL"

# -----------------------------------------------------------------------------
# Run in isolated venv
# -----------------------------------------------------------------------------
(
  timing_mark "start_qualityCollectVenvSetup"

  cd "$WT_ROOT"
  python -m venv .qc-venv
  # shellcheck disable=SC1091
  source .qc-venv/bin/activate
  python -m pip install -U pip wheel

  python -V > "$OUT_ABS/python_version.txt" || true
  uname -a  > "$OUT_ABS/uname.txt" || true

  # --- optional per-repo overrides -------------------------------------------
  if [[ -f "$REPO_SETUP_FILE" ]]; then
    echo "Using per-repo test setup: $REPO_SETUP_FILE"
    # shellcheck disable=SC1090
    source "$REPO_SETUP_FILE"
  else
    echo "No per-repo setup found at: $REPO_SETUP_FILE (using defaults)"
  fi

  # --- Default install: simplified -------------------------------------------
  default_install() {
    echo "Default install (simplified): trying common patterns"

    # 1) Prefer common test extras if present
    for extra in test tests dev ci; do
      echo ">> pip install -e .[${extra}] (best-effort)"
      python -m pip install -e ".[${extra}]" >/dev/null 2>&1 && {
        echo "Installed editable with extras: [${extra}]"
        break
      } || true
    done

    # 2) If editable install didn't happen above, at least install base package
    echo ">> pip install -e . (best-effort)"
    python -m pip install -e . >/dev/null 2>&1 || true

    # 3) requirements-dev.txt is a common convention
    if [[ -f "requirements-dev.txt" ]]; then
      echo ">> pip install -r requirements-dev.txt (best-effort)"
      python -m pip install -r requirements-dev.txt || true
    fi

    # 4) Ensure pytest tooling exists
    echo ">> pip install pytest pytest-cov pytest-timeout"
    python -m pip install pytest pytest-cov pytest-timeout || true
  }

  if declare -f QUALITY_INSTALL >/dev/null 2>&1; then
    echo "Using custom QUALITY_INSTALL for $REPO_NAME"
    QUALITY_INSTALL
  else
    default_install
  fi

  timing_mark "end_qualityCollectVenvSetup"

  # --- Pytest runner (simplified: no benchmark/xdist auto-magic) --------------
  default_pytest_run() {
    export WATCHDOG_FORCE_POLLING=1

    # Ensure in-tree import wins (kept, because many repos assume this)
    _pp="${PYTHONPATH:-}"
    export PYTHONPATH=".:${PYTHONPATH:-}"
    [[ -d "src" ]] && export PYTHONPATH="src:${PYTHONPATH:-}"
    for tdir in tests test t; do
      [[ -d "$tdir" ]] && export PYTHONPATH="$tdir:${PYTHONPATH:-}"
    done

    : "${PYTEST_TIMEOUT:=180}"
    : "${COV_FAIL_UNDER:=0}"
    : "${PYTEST_WALLTIME:=}"          # optional: e.g. 15m

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
      ${PYTEST_ADDOPTS:+$PYTEST_ADDOPTS} \
      2>&1 | tee "$TEST_LOG" || true

    PYTEST_RC=${PIPESTATUS[0]}
    export PYTHONPATH="$_pp"
    if [[ $PYTEST_RC -ne 0 ]]; then
      echo "pytest failed with exit code $PYTEST_RC" >&2
      exit $PYTEST_RC
    fi
  }

  timing_mark "start_pytest"
  if declare -f QUALITY_TEST >/dev/null 2>&1; then
    echo "Using custom QUALITY_TEST for $REPO_NAME"
    QUALITY_TEST
  else
    default_pytest_run
  fi
  timing_mark "end_pytest"

  # --- Install analysis tooling best-effort (don’t break the run) -------------
  # Intentionally after tests so test failures stay “pure”.
  python -m pip install ruff radon vulture bandit pip-audit requests pyyaml mando >/dev/null 2>&1 || true
  python -m pip install mypy >/dev/null 2>&1 || true

  python -m pip freeze > "$OUT_ABS/pip_freeze.txt" || true
  {
    echo -n "pytest: "; pytest --version || true
    echo -n "ruff: "; ruff --version || true
    echo -n "mypy: "; mypy --version || true
    echo -n "radon: "; radon --version || true
    echo -n "vulture: "; vulture --version || true
    echo -n "bandit: "; bandit --version || true
    echo -n "pip-audit: "; pip-audit --version || true
  } > "$OUT_ABS/tool_versions.txt" || true

  # --- Static checks (best-effort; never crash the whole run) -----------------
  mapfile -d '' PY_FILES < <(
    for p in "${SRC_PATHS[@]}"; do
      case "$p" in tests|test|t|docs|doc|build|dist|.venv|venv|.qc-venv|.git) continue ;; esac
      [[ -d "$p" ]] && find "$p" -type f -name '*.py' -print0
    done
  )

  timing_mark "start_ruff"
  echo "Time for Ruff"
  if command -v ruff >/dev/null 2>&1; then
    ruff_targets=()
    for p in "${SRC_PATHS[@]}"; do
      case "$p" in tests|test|t|docs|doc|build|dist|.venv|venv|.qc-venv|.git) continue ;; esac
      [[ -d "$p" ]] && ruff_targets+=("$p")
    done
    ((${#ruff_targets[@]})) && ruff check --output-format=json \
      --exclude ".git,.qc-venv,.venv,venv,build,dist,tests,test,t" \
      "${ruff_targets[@]}" > "$OUT_ABS/ruff.json" || true
  fi
  timing_mark "end_ruff"

  timing_mark "start_mypy"
  echo "Time for Mypy"
  if command -v mypy >/dev/null 2>&1; then
    mypy --hide-error-context --no-error-summary . > "$OUT_ABS/mypy.txt" || true
  fi
  timing_mark "end_mypy"

  timing_mark "start_radon"
  echo "Time for Radon"
  if command -v radon >/dev/null 2>&1 && ((${#PY_FILES[@]})); then
    radon cc -j "${PY_FILES[@]}" > "$OUT_ABS/radon_cc.json" || true
    radon mi -j "${PY_FILES[@]}" > "$OUT_ABS/radon_mi.json" || true
  fi
  timing_mark "end_radon"

  timing_mark "start_vulture"
  echo "Time for Vulture"
  if command -v vulture >/dev/null 2>&1 && ((${#PY_FILES[@]})); then
    vulture "${PY_FILES[@]}" > "$OUT_ABS/vulture.txt" || true
  fi
  timing_mark "end_vulture"

  #timing_mark "start_bandit"
  #echo "Time for Bandit"
  #if command -v bandit >/dev/null 2>&1; then
  #  bandit -q -r "${SRC_PATHS[@]}" -f json -o "$OUT_ABS/bandit.json" || true
  #fi
  #timing_mark "end_bandit"

  #timing_mark "start_pipAudit"
  #echo "Time for Pip-audit"
  #if command -v pip-audit >/dev/null 2>&1; then
  #  pip-audit -f json -o "$OUT_ABS/pip_audit.json" || true
  #fi
  #timing_mark "end_pipAudit"

  #timing_mark "start_pyExamine"
  #echo "Time for PyExamine"
  #if command -v analyze_code_quality >/dev/null 2>&1; then
  #  PYX_DIR="$OUT_ABS/pyexamine"; mkdir -p "$PYX_DIR"
  #  : "${PYX_TIMEOUT:=3m}"
  #  idx=0
  #  for p in "${SRC_PATHS[@]}"; do
  #    case "$p" in tests|test|t|docs|doc|build|dist|.venv|venv|.qc-venv|.git) continue ;; esac
  #    [[ -d "$p" ]] || continue
  #    base="$PYX_DIR/code_quality_report_${idx}"
  #    echo "PyExamine: $p -> $base"
  #    timeout -k 10s "$PYX_TIMEOUT" \
  #      analyze_code_quality "$WT_ROOT/$p" \
  #        --config "/opt/configs/pyexamine_fast.yaml" \
  #        --output "$base" || echo "PyExamine timed out or failed on $p" >&2
  #    idx=$((idx+1))
  #  done
  #fi
  #timing_mark "end_pyExamine"
)

echo "==> Collected metrics in $OUT_ABS"
