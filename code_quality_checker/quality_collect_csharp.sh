#!/usr/bin/env bash
# Usage:
#   ./quality_collect_csharp.sh <REPO_PATH> [LABEL]
#
# Writes to: OUT_DIR if set, else .quality/<repo>/<label>
set -euo pipefail

export TZ=UTC
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <REPO_PATH> [LABEL]" >&2
  exit 2
fi

REPO_PATH="$(realpath "$1")"
REPO_NAME="$(basename "$REPO_PATH")"
LABEL="${2:-current}"

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

if [[ $IS_GIT -eq 1 ]]; then
  git -C "$WT_ROOT" rev-parse --short HEAD > "$OUT_ABS/git_sha.txt" || true
  git -C "$WT_ROOT" branch --show-current  > "$OUT_ABS/git_branch.txt" || true
fi

echo "Repo: $REPO_PATH"
echo "Worktree: $WT_ROOT  Label: $LABEL"
echo "Out: $OUT_ABS"

cd "$WT_ROOT"

dotnet --info > "$OUT_ABS/dotnet_info.txt" 2>&1 || true

pick_test_target() {
  local root="$1"

  # 1) Prefer a solution (shortest path).
  local sln
  sln="$(find "$root" -name '*.sln' -not -path '*/.git/*' \
    | awk '{ print length, $0 }' | sort -n | head -n1 | cut -d' ' -f2- || true)"
  if [[ -n "${sln:-}" ]]; then
    echo "$sln"
    return 0
  fi

  # 2) Otherwise, try a test project.
  local csproj
  csproj="$(find "$root" \( -name '*Tests*.csproj' -o -name '*.Tests.csproj' \) -not -path '*/.git/*' \
    | awk '{ print length, $0 }' | sort -n | head -n1 | cut -d' ' -f2- || true)"
  if [[ -n "${csproj:-}" ]]; then
    echo "$csproj"
    return 0
  fi

  echo ""
  return 0
}

TARGET="$(pick_test_target "$WT_ROOT")"
printf '%s\n' "$TARGET" > "$OUT_ABS/test_target.txt"

LOG="$OUT_ABS/dotnet_test.log"
RC_FILE="$OUT_ABS/dotnet_test_exit_code.txt"
TRX_DIR="$OUT_ABS/test_results"
mkdir -p "$TRX_DIR"

: "${DOTNET_TEST_TIMEOUT:=20m}"

set +e
if [[ -n "${TARGET:-}" ]]; then
  echo "Running: dotnet test $TARGET"
  timeout -k 30s "$DOTNET_TEST_TIMEOUT" \
    dotnet test "$TARGET" \
      --nologo \
      /p:CollectCoverage=false \
      --logger "trx" \
      --results-directory "$TRX_DIR" \
      2>&1 | tee "$LOG"
else
  echo "No .sln or test csproj found; trying dotnet test from repo root"
  timeout -k 30s "$DOTNET_TEST_TIMEOUT" \
    dotnet test \
      --nologo \
      /p:CollectCoverage=false \
      --logger "trx" \
      --results-directory "$TRX_DIR" \
      2>&1 | tee "$LOG"
fi
RC=${PIPESTATUS[0]}
set -e

echo "$RC" > "$RC_FILE"
if [[ $RC -ne 0 ]]; then
  echo "dotnet test failed with exit code $RC" >&2
  exit $RC
fi

echo "==> Collected test results in $OUT_ABS"
