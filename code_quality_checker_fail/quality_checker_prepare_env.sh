#!/usr/bin/env bash
# Usage:
#   ./quality_checker_prepare_env.sh <REPO_PATH> --python <PYBIN>
#
# If uv.lock exists: export pinned reqs (filtered) and install into the given venv, then -e .
# Else: pyproject editable or requirements*.txt
# Ensure analyzers (ruff/mypy/radon/vulture/bandit/pip-audit/pytest-cov/pytest-timeout) present.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <REPO_PATH> --python <PYBIN>" >&2
  exit 2
fi

REPO_PATH=""
PYBIN=""
while (( "$#" )); do
  case "${1:-}" in
    --python) shift; PYBIN="${1:-}"; [[ -z "$PYBIN" ]] && { echo "Missing value after --python"; exit 2; }; shift ;;
    *)        REPO_PATH="$(realpath "$1")"; shift ;;
  esac
done

[[ -d "$REPO_PATH" ]] || { echo "Error: repo path not found: $REPO_PATH" >&2; exit 1; }
[[ -n "$PYBIN"     ]] || { echo "Error: --python <PYBIN> is required." >&2; exit 1; }

QUALITY_UV_EXPORT_FLAGS="${QUALITY_UV_EXPORT_FLAGS:---locked --all-groups --all-extras}"

"$PYBIN" -m pip install -U pip >/dev/null

if [[ -f "$REPO_PATH/uv.lock" ]]; then
  command -v uv >/dev/null 2>&1 || { echo "Error: uv.lock present but 'uv' not on PATH." >&2; exit 1; }

  echo "==> Exporting pinned requirements from uv.lock (${QUALITY_UV_EXPORT_FLAGS})"
  REQ_ALL="$(mktemp)"
  (
    cd "$REPO_PATH"
    # shellcheck disable=SC2086
    uv export $QUALITY_UV_EXPORT_FLAGS --format requirements-txt > "$REQ_ALL"
  )
  [[ -s "$REQ_ALL" ]] || { echo "Error: exported requirements file is empty." >&2; rm -f "$REQ_ALL"; exit 1; }

  REQ_FILTERED="$(mktemp)"
  grep -Ev '^\s*-e\s|@\s*file://|^file://|^\s*\./|^\s*\.\./' "$REQ_ALL" > "$REQ_FILTERED"

  echo "==> Installing exported (filtered) requirements into test venv"
  "$PYBIN" -m pip install -r "$REQ_FILTERED"

  echo "==> Installing project (editable) into the same venv"
  "$PYBIN" -m pip install -e "$REPO_PATH"

  rm -f "$REQ_ALL" "$REQ_FILTERED"

elif [[ -f "$REPO_PATH/pyproject.toml" ]]; then
  echo "==> Installing from pyproject.toml (editable)"
  "$PYBIN" -m pip install -e "$REPO_PATH"

elif compgen -G "$REPO_PATH/requirements*.txt" >/dev/null; then
  if [[ -f "$REPO_PATH/requirements.txt" ]]; then
    echo "==> Installing from requirements.txt"
    "$PYBIN" -m pip install -r "$REPO_PATH/requirements.txt"
  else
    FIRST_REQ="$(ls "$REPO_PATH"/requirements*.txt | head -n1)"
    echo "==> Installing from $(basename "$FIRST_REQ")"
    "$PYBIN" -m pip install -r "$FIRST_REQ"
  fi

else
  echo "Error: no uv.lock, pyproject.toml, or requirements*.txt found in $REPO_PATH" >&2
  exit 1
fi

echo "==> Ensuring analysis tools (ruff, mypy, radon, vulture, bandit, pip-audit, pytest-cov, pytest-timeout)"
ANALYZERS=${QUALITY_ANALYZERS:-"ruff mypy radon vulture bandit pip-audit pytest-cov pytest-timeout"}
"$PYBIN" -m pip install --upgrade-strategy only-if-needed $ANALYZERS

echo "==> Verifying pytest plugins import from this venv"
"$PYBIN" - <<'PY'
import sys
for mod in ("pytest","pytest_timeout","pytest_cov"):
    try:
        __import__(mod)
    except Exception as e:
        print(f"Error: required test module not importable in this venv: {mod}: {e}", file=sys.stderr)
        sys.exit(1)
print("OK: pytest, pytest-timeout, pytest-cov importable.")
PY

echo "==> Environment ready."
