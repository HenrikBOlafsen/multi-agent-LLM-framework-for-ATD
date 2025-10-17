#!/usr/bin/env bash
# Usage:
#   ./quality_collect.sh <REPO_PATH> [LABEL] [SRC_HINT]
# Examples:
#   ./quality_collect.sh projects_to_analyze/kombu main kombu
#   ./quality_collect.sh projects_to_analyze/kombu refactor-branch kombu
#
# Writes to: .quality/<repo_name>/<label>
set -euo pipefail

# --- reproducibility controls (deterministic-ish runs) ---
export PYTHONHASHSEED=0
export TZ=UTC


if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <REPO_PATH> [LABEL] [SRC_HINT]" >&2
  exit 2
fi

REPO_PATH="$(realpath "$1")"
REPO_NAME="$(basename "$REPO_PATH")"

# --- detect if repo is a git work tree ---------------------------------------
IS_GIT=0
if git -C "$REPO_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IS_GIT=1
fi

# Label defaults to current branch (if git) or "current"
DEFAULT_LABEL="current"
if [[ $IS_GIT -eq 1 ]]; then
  DEFAULT_LABEL="$(git -C "$REPO_PATH" branch --show-current 2>/dev/null || echo current)"
fi
LABEL="${2:-$DEFAULT_LABEL}"

# Optional hint for source roots under the repo (e.g., "src" or "werkzeug")
SRC_HINT="${3:-}"

# ---- output dir --------------------------------------------------------------
# Preferred (exact) target if provided by caller:
#   OUT_DIR=/path/to/final/dir  ./quality_collect.sh ...
# Back-compat default: OUT_ROOT/<repo>/<label>
OUT_ROOT="${OUT_ROOT:-.quality}"
if [[ -n "${OUT_DIR:-}" ]]; then
  FINAL_OUT_DIR="$OUT_DIR"
else
  FINAL_OUT_DIR="$OUT_ROOT/$REPO_NAME/$LABEL"
fi
mkdir -p "$FINAL_OUT_DIR"
OUT_ABS="$(realpath "$FINAL_OUT_DIR")"

# --- monotonic run timestamp (UTC) ---
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$OUT_ABS/run_started_utc.txt" 2>/dev/null || true

# --- helpers ------------------------------------------------------------------
detect_src_paths() {
  local root="$1"; local hint="${2:-}"
  local -a found=()

  # Prefer explicit hint if it exists
  if [[ -n "$hint" && -d "$root/$hint" ]]; then
    found+=("$hint")
  fi

  # Common “src/” layout: packages with __init__.py
  if [[ -d "$root/src" ]]; then
    while IFS= read -r -d '' pkg; do
      found+=("src/$(basename "$pkg")")
    done < <(find "$root/src" -mindepth 1 -maxdepth 1 -type d -exec test -e '{}/__init__.py' \; -print0)
  fi

  # Flat layout: top-level packages with __init__.py (skip hidden/venv/build/tests)
  while IFS= read -r -d '' pkg; do
    base="$(basename "$pkg")"
    [[ "$base" =~ ^(\.|_|\-)?(venv|.venv|build|dist|tests?)$ ]] && continue
    found+=("$base")
  done < <(find "$root" -mindepth 1 -maxdepth 1 -type d -exec test -e '{}/__init__.py' \; -print0)

  # De-duplicate while preserving order
  awk -v RS='\0' '!seen[$0]++ {print}' < <(printf '%s\0' "${found[@]}") 2>/dev/null || printf '%s\n' "${found[@]}"
}

install_test_deps() {
  # Best-effort dependency bootstrap for tests.
  # Tries: pyproject extras -> requirements files -> poetry -> tox/nox -> safety net.
  local root="$1"
  python - <<'PY' "$root"
import sys, os, subprocess, io
root=sys.argv[1]

def run(cmd):
    try:
        print(">>", " ".join(cmd))
        return subprocess.call(cmd)==0
    except FileNotFoundError:
        return False

# 0) ensure pip is recent
run(["python","-m","pip","install","-U","pip"])

# 1) pyproject extras (PEP 621 optional-dependencies)
py = os.path.join(root,"pyproject.toml")
picked=[]
if os.path.isfile(py):
    try:
        import tomllib
        with open(py,"rb") as f:
            data=tomllib.load(f)
        opt = (data.get("project",{}) or {}).get("optional-dependencies",{}) or {}
        candidates = ["dev","test","tests","ci","all"]
        picked = [e for e in candidates if e in opt]
        if picked:
            if run(["python","-m","pip","install","-e", f"{root}[{','.join(picked)}]"]):
                sys.exit(0)
    except Exception:
        pass

# 2) common requirements files
for f in ("requirements-dev.txt","requirements/test.txt","requirements-tests.txt","requirements.txt","dev-requirements.txt"):
    p=os.path.join(root,f)
    if os.path.isfile(p):
        run(["python","-m","pip","install","-r",p])

# 3) poetry
poetry_toml_has=False
if os.path.isfile(py):
    try:
        with open(py,"r",encoding="utf-8") as fh:
            poetry_toml_has = "[tool.poetry]" in fh.read()
    except Exception:
        pass
if os.path.isfile(os.path.join(root,"poetry.lock")) or poetry_toml_has:
    run(["python","-m","pip","install","poetry"])
    run(["poetry","install","--with","dev,test"])

# 3.5) ensure the project-under-test (and its install_requires) are installed
# This is the key bit that pulls in runtime deps like "MarkupSafe" for Werkzeug.
run(["python","-m","pip","install", root])

# 4) tox / nox tooling present (don't run tests here!)
run(["python","-m","pip","install","tox","nox"])

# Try to create tox envs without running tests (helps pull dev deps in some repos)
# It's okay if this no-ops or fails; we still fall back below.
run(["tox","-q","-r","-e","py","--notest"])

# 5) safety net: common test deps
run(["python","-m","pip","install",
     "pytest","pytest-cov","pytest-timeout","pytest-xdist",
     "trustme","watchdog","blinker","greenlet","typing-extensions",
     "ephemeral-port-reserve"])
sys.exit(0)
PY
}

# --- choose workspace root (git worktree for a label, else REPO_PATH) --------
WT_DIR=""          # temp worktree (if git)
WT_ROOT="$REPO_PATH"

if [[ $IS_GIT -eq 1 ]]; then
  # Make sure we have the ref (branch/remote/sha) locally
  git -C "$REPO_PATH" fetch --all --quiet || true
  if ! git -C "$REPO_PATH" rev-parse --verify --quiet "${LABEL}^{commit}" >/dev/null; then
    # Try fetching the label from any remote if not resolvable yet
    for r in $(git -C "$REPO_PATH" remote); do
      git -C "$REPO_PATH" fetch "$r" "$LABEL:$LABEL" && break || true
    done
  fi
  if ! git -C "$REPO_PATH" rev-parse --verify --quiet "${LABEL}^{commit}" >/dev/null; then
    echo "Error: ref '$LABEL' not found (even after fetch) in $REPO_PATH" >&2
    exit 1
  fi

  # Create a detached worktree at the target ref
  WT_DIR="$(mktemp -d -t qcwt.XXXXXX)"
  git -C "$REPO_PATH" worktree add --detach "$WT_DIR" "$LABEL" >/dev/null
  WT_ROOT="$WT_DIR"

  # Ensure clean removal of the worktree on exit
  cleanup() {
    git -C "$REPO_PATH" worktree remove --force "$WT_DIR" 2>/dev/null || true
    rm -rf "$WT_DIR" 2>/dev/null || true
  }
  trap cleanup EXIT
fi

CUR_SHA="unknown"
CUR_BRANCH="detached"
if [[ $IS_GIT -eq 1 ]]; then
  CUR_SHA="$(git -C "$WT_ROOT" rev-parse --short HEAD)"
  CUR_BRANCH="$(git -C "$WT_ROOT" symbolic-ref --short -q HEAD || echo detached)"
  echo "==> [$REPO_NAME] worktree at $LABEL @ $CUR_SHA (branch: $CUR_BRANCH)"
else
  echo "==> [$REPO_NAME] non-git directory; analyzing current files"
fi

# ---- detect sources on this ref ---------------------------------------------
mapfile -t SRC_PATHS < <(detect_src_paths "$WT_ROOT" "$SRC_HINT")
[[ ${#SRC_PATHS[@]} -eq 0 ]] && SRC_PATHS=(".")

# Persist traceability *before* running tools
printf '%s\n' "${SRC_PATHS[@]}" > "$OUT_ABS/src_paths.txt"
printf '%s\n' "$CUR_SHA"        > "$OUT_ABS/git_sha.txt"
printf '%s\n' "$CUR_BRANCH"     > "$OUT_ABS/git_branch.txt"

echo "Repo:   $REPO_PATH"
echo "Label:  $LABEL"
echo -n "Src(s): "; printf '%s ' "${SRC_PATHS[@]}"; echo
echo "Out:    $OUT_ABS"

echo "==> Collecting quality metrics"
echo "Repo:    $WT_ROOT"
echo "Label:   $LABEL"
echo -n "Src(s):  "; printf '%s ' "${SRC_PATHS[@]}"; echo
echo "Out:     $OUT_ABS"

# --- context ------------------------------------------------------------------
python -V > "$OUT_ABS/python_version.txt" || true
if [[ $IS_GIT -eq 1 ]]; then
  git -C "$WT_ROOT" rev-parse --short HEAD > "$OUT_ABS/git_sha.txt" || true
  git -C "$WT_ROOT" branch --show-current  > "$OUT_ABS/git_branch.txt" || true
fi
uname -a > "$OUT_ABS/uname.txt" 2>/dev/null || true


# Helper: expand tool args for multiple src paths
cov_args=()
radon_targets=()
vulture_targets=()
bandit_targets=()
for p in "${SRC_PATHS[@]}"; do
  cov_args+=( "--cov=$p" )
  radon_targets+=( "$p" )
  vulture_targets+=( "$p" )
  bandit_targets+=( "$p" )
done

# --- run tools inside the worktree (or repo path if non-git) -----------------
(
  cd "$WT_ROOT"

  # Best-effort install of test/dev deps for this repo
  install_test_deps "$WT_ROOT"

  # Snapshot the exact Python packages and tool versions used
  python -m pip freeze > "$OUT_ABS/pip_freeze.txt" 2>/dev/null || true
  {
    echo -n "pytest: ";    (pytest --version    2>/dev/null || true)
    echo -n "ruff: ";      (ruff --version      2>/dev/null || true)
    echo -n "mypy: ";      (mypy --version      2>/dev/null || true)
    echo -n "radon: ";     (radon --version     2>/dev/null || true)
    echo -n "vulture: ";   (vulture --version   2>/dev/null || true)
    echo -n "bandit: ";    (bandit --version    2>/dev/null || true)
    echo -n "pip-audit: "; (pip-audit --version 2>/dev/null || true)
  } > "$OUT_ABS/tool_versions.txt"


  # Avoid watchdog backend issues in containers
  export WATCHDOG_FORCE_POLLING=1

  # Functionality (tests) + coverage XML
  if command -v pytest >/dev/null 2>&1; then
    _pp="${PYTHONPATH:-}"
    [[ -d "src" ]] && export PYTHONPATH="src:${PYTHONPATH:-}"

    test_arg="."
    [[ -d "tests" ]] && test_arg="tests"

    # Always capture the full test log so errors don't scroll away
    TEST_LOG="$OUT_ABS/pytest_full.log"

    # If the repo defines a nox test session, prefer it (projects often rely on it)
    if [[ -f "noxfile.py" ]] && command -v nox >/dev/null 2>&1; then
      # Pass through junitxml + coverage options to pytest via nox’ “--” passthrough
      # Many Pallets-style repos (like Werkzeug) expect to be run this way.
      nox -s tests -- \
        -n 0 \
        -q --disable-warnings \
        --timeout=20 --timeout-method=thread \
        --durations=25 \
        --junitxml "$OUT_ABS/pytest.xml" \
        "${cov_args[@]}" --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
        "$test_arg" 2>&1 | tee "$TEST_LOG" || true
    else
      # Fallback: run pytest directly
      pytest -q \
        -n 0 \
        --disable-warnings \
        --timeout=20 --timeout-method=thread \
        --durations=25 \
        --junitxml "$OUT_ABS/pytest.xml" \
        "${cov_args[@]}" --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
        "$test_arg" 2>&1 | tee "$TEST_LOG" || true
    fi

    export PYTHONPATH="$_pp"
  else
    echo "pytest not found; skipping tests & coverage" >&2
  fi


  # Readability / standards (ruff)
  if command -v ruff >/dev/null 2>&1; then
    ruff_targets=("${SRC_PATHS[@]}"); [[ ${#ruff_targets[@]} -eq 0 ]] && ruff_targets=(".")
    ruff check --select ALL --ignore D203,D213 --output-format=json "${ruff_targets[@]}" \
      | tee "$OUT_ABS/ruff.json" || true
  else
    echo "ruff not found; skipping lint" >&2
  fi

  # Types (mypy)
  if command -v mypy >/dev/null 2>&1; then
    mypy --hide-error-context --no-error-summary . \
      | tee "$OUT_ABS/mypy.txt" || true
  else
    echo "mypy not found; skipping type check" >&2
  fi

  # Maintainability
  if command -v radon >/dev/null 2>&1; then
    radon cc -j "${radon_targets[@]}" > "$OUT_ABS/radon_cc.json" || true
    radon mi -j "${radon_targets[@]}" > "$OUT_ABS/radon_mi.json" || true
  fi

  # Dead code
  if command -v vulture >/dev/null 2>&1; then
    vulture "${vulture_targets[@]}" > "$OUT_ABS/vulture.txt" || true
  fi

  # Security
  if command -v bandit >/dev/null 2>&1; then
    bandit -q -r "${bandit_targets[@]}" -f json -o "$OUT_ABS/bandit.json" || true
  fi
  if command -v pip-audit >/dev/null 2>&1; then
    pip-audit -f json -o "$OUT_ABS/pip_audit.json" || true
  fi

  # PyExamine (Code Quality Analyzer)
  if command -v analyze_code_quality >/dev/null 2>&1; then
    PYX_DIR="$OUT_ABS/pyexamine"; mkdir -p "$PYX_DIR"

    # 15-minute cap per source root; adjust if you like
    PYX_TIMEOUT="${PYX_TIMEOUT:-15m}"

    idx=0
    for p in "${SRC_PATHS[@]}"; do
      # Skip common non-source dirs defensively
      case "$p" in
        tests|test|t|docs|doc|build|dist|.venv|venv) continue;;
      esac

      base="$PYX_DIR/code_quality_report_${idx}"
      echo "PyExamine on source root: $p  →  $base"
      # Run with your default config baked into the image
      # timeout exits non-zero if it hits the cap; we don’t fail the whole run
      timeout -k 10s "$PYX_TIMEOUT" \
        analyze_code_quality "$WT_ROOT/$p" \
        --config "/opt/configs/pyexamine_default.yaml" \
        --output "$base" || echo "PyExamine timed out or failed on $p" >&2
      idx=$((idx+1))
    done
  else
    echo "PyExamine (analyze_code_quality) not found; skipping." >&2
  fi



)

echo "==> Collected metrics in $OUT_ABS"
