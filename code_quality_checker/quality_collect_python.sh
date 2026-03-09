#!/usr/bin/env bash
#
# Usage:
#   ./quality_collect_python.sh <REPO_PATH> [LABEL] [SRC_HINT]
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

rm -rf "$FINAL_OUT_DIR"
mkdir -p "$FINAL_OUT_DIR"

OUT_ABS="$(realpath "$FINAL_OUT_DIR")"

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

echo "Repo: $REPO_PATH"
echo "Worktree: $WT_ROOT  Label: $LABEL"
echo -n "Sources: "; printf '%s ' "${SRC_PATHS[@]}"; echo
echo "Out: $OUT_ABS"

# --- Per-repo setup discovery ------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SETUP_DIR="${REPO_SETUP_DIR:-$SCRIPT_DIR/repo-test-setups-python}"
REPO_SETUP_FILE="$REPO_SETUP_DIR/${REPO_NAME}-test-setup.sh"

# -----------------------------------------------------------------------------
# Run in isolated venv
# -----------------------------------------------------------------------------
(
  cd "$WT_ROOT"
  python -m venv .qc-venv
  # shellcheck disable=SC1091
  source .qc-venv/bin/activate
  python -m pip install -U pip wheel

  if [[ -f "$REPO_SETUP_FILE" ]]; then
    echo "Using per-repo test setup: $REPO_SETUP_FILE"
    # shellcheck disable=SC1090
    source "$REPO_SETUP_FILE"
  else
    echo "No per-repo setup found at: $REPO_SETUP_FILE (using defaults)"
  fi

  # --- Default install -------------------------------------------------------
  default_install() {
    echo "Default install (simplified): trying common patterns"

    for extra in test tests dev ci; do
      echo ">> pip install -e .[${extra}] (best-effort)"
      python -m pip install -e ".[${extra}]" >/dev/null 2>&1 && {
        echo "Installed editable with extras: [${extra}]"
        break
      } || true
    done

    echo ">> pip install -e . (best-effort)"
    python -m pip install -e . >/dev/null 2>&1 || true

    if [[ -f "requirements-dev.txt" ]]; then
      echo ">> pip install -r requirements-dev.txt (best-effort)"
      python -m pip install -r requirements-dev.txt || true
    fi

    echo ">> pip install pytest pytest-cov pytest-timeout"
    python -m pip install pytest pytest-cov pytest-timeout || true
  }

  if declare -f QUALITY_INSTALL >/dev/null 2>&1; then
    echo "Using custom QUALITY_INSTALL for $REPO_NAME"
    QUALITY_INSTALL
  else
    default_install
  fi

  # --- Pytest runner ---------------------------------------------------------
  default_pytest_run() {
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
      ${PYTEST_ADDOPTS:+$PYTEST_ADDOPTS} \
      2>&1 | tee "$TEST_LOG" || true

    PYTEST_RC=${PIPESTATUS[0]}
    export PYTHONPATH="$_pp"
    if [[ $PYTEST_RC -ne 0 ]]; then
      echo "pytest failed with exit code $PYTEST_RC" >&2
      exit $PYTEST_RC
    fi
  }

  if declare -f QUALITY_TEST >/dev/null 2>&1; then
    echo "Using custom QUALITY_TEST for $REPO_NAME"
    QUALITY_TEST
  else
    default_pytest_run
  fi

  # --- Install analysis tooling ---------------------------------------------
  python -m pip install ruff radon vulture >/dev/null 2>&1 || true

  # --- Static checks ---------------------------------------------------------
  mapfile -d '' PY_FILES < <(
    for p in "${SRC_PATHS[@]}"; do
      case "$p" in tests|test|t|docs|doc|build|dist|.venv|venv|.qc-venv|.git) continue ;; esac
      [[ -d "$p" ]] && find "$p" -type f -name '*.py' -print0
    done
  )

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

  echo "Time for Radon"
  if command -v radon >/dev/null 2>&1 && ((${#PY_FILES[@]})); then
    radon cc -j "${PY_FILES[@]}" > "$OUT_ABS/radon_cc.json" || true
    radon mi -j "${PY_FILES[@]}" > "$OUT_ABS/radon_mi.json" || true
  fi

  echo "Time for Vulture"
  if command -v vulture >/dev/null 2>&1 && ((${#PY_FILES[@]})); then
    vulture "${PY_FILES[@]}" > "$OUT_ABS/vulture.txt" || true
  fi
)

echo "==> Collected metrics in $OUT_ABS"