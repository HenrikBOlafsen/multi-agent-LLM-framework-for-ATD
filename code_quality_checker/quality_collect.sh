#!/usr/bin/env bash
# Usage:
#   ./quality_collect.sh <REPO_PATH> [LABEL] [SRC_HINT]
# Example:
#   ./quality_collect.sh projects/kombu main kombu
#
# Writes to: .quality/<repo>/<label>
set -euo pipefail

export PYTHONHASHSEED=0
export TZ=UTC

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <REPO_PATH> [LABEL] [SRC_HINT]" >&2
  exit 2
fi

REPO_PATH="$(realpath "$1")"
REPO_NAME="$(basename "$REPO_PATH")"
LABEL="${2:-current}"          # default label if not a git repo
SRC_HINT="${3:-}"              # e.g., "src/werkzeug" or "kombu"

# --- Git worktree (isolated checkout) -----------------------------------------
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
  git -C "$REPO_PATH" fetch --all --quiet || true
  if ! git -C "$REPO_PATH" rev-parse --verify --quiet "${LABEL}^{commit}" >/dev/null; then
    echo "Ref '$LABEL' not found in $REPO_PATH" >&2
    exit 1
  fi
  WT_DIR="$(mktemp -d -t qcwt.XXXXXX)"
  git -C "$REPO_PATH" worktree add --detach "$WT_DIR" "$LABEL" >/dev/null
  WT_ROOT="$WT_DIR"
  cleanup() {
    git -C "$REPO_PATH" worktree remove --force "$WT_DIR" 2>/dev/null || true
    rm -rf "$WT_DIR" 2>/dev/null || true
  }
  trap cleanup EXIT
fi

# --- Source detection (simple & predictable) -----------------------------------
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
    [[ "$base" =~ ^(\.|_|\-)?(venv|.venv|build|dist|tests?)$ ]] && continue
    found+=("$base")
  done < <(find "$root" -mindepth 1 -maxdepth 1 -type d -exec test -e '{}/__init__.py' \; -print0)
  # de-dupe
  awk -v RS='\0' '!seen[$0]++{print}' < <(printf '%s\0' "${found[@]}") 2>/dev/null || printf '%s\n' "${found[@]}"
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

# --- Per-run venv (isolation) -------------------------------------------------
(
  cd "$WT_ROOT"
  python -m venv .qc-venv
  # shellcheck disable=SC1091
  source .qc-venv/bin/activate
  python -m pip install -U pip wheel

  # --- Minimal install: project + test plugins --------------------------------
  # 1) install project (editable)
  python -m pip install -e .

  # 1.1) install *all* optional extras if defined (fail loud if it can't resolve)
  EXTRAS="$(python - <<'PY'
import tomllib
try:
    with open("pyproject.toml","rb") as f:
        data = tomllib.load(f)
    opt = (data.get("project",{}) or {}).get("optional-dependencies") or {}
    extras = sorted(opt.keys())
    if extras:
        print(",".join(extras))
except Exception:
    pass
PY
)"
  if [[ -n "$EXTRAS" ]]; then
    echo "Installing extras: [$EXTRAS]"
    python -m pip install -e ".[${EXTRAS}]"
  fi

  # 1.2) install PEP 735 dependency-groups commonly used for tests
  # We intentionally only pull 'tests' (and 'test' if present) to stay general.
  GROUP_REQS="$(python - <<'PY'
import sys, tomllib, json
try:
    with open("pyproject.toml","rb") as f:
        data = tomllib.load(f)
    groups = (data.get("dependency-groups") or {})
    wanted = []
    for key in ("tests","test"):
        if key in groups and isinstance(groups[key], list):
            wanted.extend(groups[key])
    if wanted:
        print(json.dumps(wanted))
except Exception:
    pass
PY
)"
  if [[ -n "$GROUP_REQS" ]]; then
    echo "Installing dependency-groups: tests/test"
    # shell-safe install of each requirement string
    python - <<'PY' "$GROUP_REQS"
import sys, json, subprocess
reqs = json.loads(sys.argv[1])
if reqs:
    cmd = ["python","-m","pip","install", *reqs]
    print(">>", " ".join(cmd))
    raise SystemExit(subprocess.call(cmd))
PY
  fi



  # 2) always have the basics we rely on (no guessing, no special cases)
  python -m pip install \
    pytest pytest-cov pytest-xdist pytest-timeout \
    ruff mypy radon vulture bandit pip-audit

  # --- Tool versions snapshot --------------------------------------------------
  python -m pip freeze > "$OUT_ABS/pip_freeze.txt" || true
  {
    echo -n "pytest: "; pytest --version    || true
    echo -n "ruff: ";   ruff --version      || true
    echo -n "mypy: ";   mypy --version      || true
    echo -n "radon: ";  radon --version     || true
    echo -n "vulture: ";vulture --version   || true
    echo -n "bandit: "; bandit --version    || true
    echo -n "pip-audit: "; pip-audit --version || true
  } > "$OUT_ABS/tool_versions.txt"

  # --- Pytest (uniform invocation) --------------------------------------------
  export WATCHDOG_FORCE_POLLING=1
  # ensure in-tree import wins
  _pp="${PYTHONPATH:-}"
  export PYTHONPATH=".:${PYTHONPATH:-}"
  [[ -d "src"  ]] && export PYTHONPATH="src:${PYTHONPATH}"
  # add common test roots so packages like "res" under tests/ are importable
  for tdir in tests test t; do
    [[ -d "$tdir" ]] && export PYTHONPATH="$tdir:${PYTHONPATH}"
  done

  # Disable 3rd-party autoload; enable only the plugins we intentionally use
  export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

  TEST_LOG="$OUT_ABS/pytest_full.log"

  # coverage targets from detected sources
  cov_args=()
  for p in "${SRC_PATHS[@]}"; do
    cov_args+=( "--cov=$p" )
  done

  # Parallelism + timeouts (plugin is installed in this venv)
  : "${PYTEST_NWORKERS:=auto}"
  : "${PYTEST_TIMEOUT:=180}"
  # Optional external wall-clock cap (e.g., PYTEST_WALLTIME=10m)
  wrap_pytest() {
    if [[ -n "${PYTEST_WALLTIME:-}" ]]; then
      timeout -k 30s "$PYTEST_WALLTIME" "$@"
    else
      "$@"
    fi
  }

  # Decide pytest import mode:
  # - default (prepend) works for most suites (e.g., Jinja)
  # - switch to importlib only if there are duplicate test basenames
  IMPORT_MODE="prepend"

  dup_basenames="$(
  python - <<'PY'
import os, glob, collections
c = collections.Counter()
for root in ("tests", "test", "t"):
    if os.path.isdir(root):
        for p in glob.glob(os.path.join(root, "**", "test_*.py"), recursive=True):
            c[os.path.basename(p)] += 1
print(1 if any(v > 1 for v in c.values()) else 0)
PY
  )"

  if [[ "$dup_basenames" == "1" ]]; then
    IMPORT_MODE="importlib"
  fi


  echo "Time for pytest"

  set -o pipefail
  : "${COV_FAIL_UNDER:=0}"   # default: don't fail the run on project coverage policy
  wrap_pytest pytest -q \
    -p pytest_cov -p pytest_timeout -p xdist.plugin \
    --import-mode="$IMPORT_MODE" \
    -n "$PYTEST_NWORKERS" --dist=worksteal \
    --disable-warnings \
    --timeout="$PYTEST_TIMEOUT" --timeout-method=thread \
    --durations=25 \
    --junitxml "$OUT_ABS/pytest.xml" \
    "${cov_args[@]}" --cov-fail-under="${COV_FAIL_UNDER:-0}" \
    --cov-report=xml:"$OUT_ABS/coverage.xml" --cov-report=term \
    ${PYTEST_ADDOPTS:+$PYTEST_ADDOPTS} \
    2>&1 | tee "$TEST_LOG" || true
  PYTEST_RC=${PIPESTATUS[0]}
  export PYTHONPATH="$_pp"
  if [[ $PYTEST_RC -ne 0 ]]; then
    echo "pytest failed with exit code $PYTEST_RC" >&2
    exit $PYTEST_RC
  fi

  # --- Static checks (fail loud if nothing to scan) ---------------------------
  # Build a real list of Python files under the detected sources
  mapfile -d '' PY_FILES < <(
    for p in "${SRC_PATHS[@]}"; do
      # skip obvious non-source dirs even if they slip into SRC_PATHS
      case "$p" in tests|test|t|docs|doc|build|dist|.venv|venv) continue ;; esac
      find "$p" -type f -name '*.py' -print0
    done
  )

  if ((${#PY_FILES[@]} == 0)); then
    echo "ERROR: no .py files found under: ${SRC_PATHS[*]}" >&2
    exit 3
  fi

  echo "Time for Ruff"
  # Ruff
  ruff_targets=()
  for p in "${SRC_PATHS[@]}"; do
    case "$p" in
      tests|test|t|docs|doc|build|dist|.venv|venv|.git|.quality) continue ;;
    esac
    [[ -d "$p" ]] && ruff_targets+=("$p")
  done

  # Add an explicit exclude to be extra safe
  ruff check --output-format=json \
    --exclude ".git,.qc-venv,.venv,venv,build,dist,tests,test,t,.quality" \
    "${ruff_targets[@]}" > "$OUT_ABS/ruff.json" || true

  echo "Time for Mypy"
  # Mypy across the repo (keeps it simple)
  mypy --hide-error-context --no-error-summary . > "$OUT_ABS/mypy.txt" || true

  echo "Time for Radon"
  # Radon on explicit file list (prevents “0 files” surprises)
  radon cc -j "${PY_FILES[@]}" > "$OUT_ABS/radon_cc.json"
  radon mi -j "${PY_FILES[@]}" > "$OUT_ABS/radon_mi.json"

  echo "Time for Vulture"
  # Vulture: use the same file list (not directories)
  vulture "${PY_FILES[@]}" > "$OUT_ABS/vulture.txt" || true

  echo "Time for Bandit"
  # Bandit prefers directories; give it the roots
  bandit -q -r "${SRC_PATHS[@]}" -f json -o "$OUT_ABS/bandit.json" || true

  echo "Time for Pip-audit"
  # Pip-audit stays repo-wide
  pip-audit -f json -o "$OUT_ABS/pip_audit.json" || true


  echo "Time for PyExamine"
  # --- PyExamine (optional; simple wall-time) ---------------------------------
  if command -v analyze_code_quality >/dev/null 2>&1; then
    PYX_DIR="$OUT_ABS/pyexamine"; mkdir -p "$PYX_DIR"
    : "${PYX_TIMEOUT:=3m}"   # default 3 minutes per source root
    idx=0
    for p in "${SRC_PATHS[@]}"; do
      case "$p" in
        tests|test|t|docs|doc|build|dist|.venv|venv) continue ;;
      esac
      base="$PYX_DIR/code_quality_report_${idx}"
      echo "PyExamine: $p -> $base"
      timeout -k 10s "$PYX_TIMEOUT" \
        analyze_code_quality "$WT_ROOT/$p" \
          --config "/opt/configs/pyexamine_fast.yaml" \
          --output "$base" || echo "PyExamine timed out or failed on $p" >&2
      idx=$((idx+1))
    done
  fi
)

echo "==> Collected metrics in $OUT_ABS"
