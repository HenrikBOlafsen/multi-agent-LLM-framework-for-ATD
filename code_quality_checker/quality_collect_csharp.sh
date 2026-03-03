#!/usr/bin/env bash
# code_quality_checker/quality_collect_csharp.sh
#
# Artifacts produced:
#   - dotnet_test.log + dotnet_test_exit_code.txt
#   - TRX files under test_results/
#   - SARIF files under sarif/ via Roslyn /errorlog (one per project+TFM+Configuration)
#   - Lizard complexity CSV under dotnet_complexity/lizard.csv
#   - provenance files (dotnet_info, targeting, etc.)
#
# NOTE:
#   We do NOT run `dotnet build` separately. `dotnet test` builds by default.
#
# Optional per-repo override file:
#   repo-test-setups-dotnet/<repo-name>-test-setup.sh
# there you can set:
#   DOTNET_WORKDIR="src"
#   DOTNET_TEST_TARGET="MyRepo.sln"
#   DOTNET_TEST_FILTER="FullyQualifiedName~Foo"
#
# Usage:
#   ./quality_collect_csharp.sh <REPO_PATH> [LABEL]
#
set -euo pipefail

export TZ=UTC
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
export DOTNET_MULTILEVEL_LOOKUP=0

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <REPO_PATH> [LABEL]" >&2
  exit 2
fi

REPO_PATH="$(realpath "$1")"
REPO_NAME="$(basename "$REPO_PATH")"
LABEL="${2:-current}"

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

# -----------------------------------------------------------------------------
# Per-repo setup discovery
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SETUP_DIR="${REPO_SETUP_DIR:-$SCRIPT_DIR/repo-test-setups-dotnet}"
REPO_SETUP_FILE="$REPO_SETUP_DIR/${REPO_NAME}-test-setup.sh"

DOTNET_WORKDIR="${DOTNET_WORKDIR:-}"
DOTNET_TEST_TARGET="${DOTNET_TEST_TARGET:-}"
DOTNET_TEST_FILTER="${DOTNET_TEST_FILTER:-}"

if [[ -f "$REPO_SETUP_FILE" ]]; then
  echo "Using per-repo test setup: $REPO_SETUP_FILE"
  # shellcheck disable=SC1090
  source "$REPO_SETUP_FILE"
else
  echo "No per-repo setup found at: $REPO_SETUP_FILE (using defaults)"
fi

{
  echo "DOTNET_WORKDIR=${DOTNET_WORKDIR:-}"
  echo "DOTNET_TEST_TARGET=${DOTNET_TEST_TARGET:-}"
  echo "DOTNET_TEST_FILTER=${DOTNET_TEST_FILTER:-}"
  echo "REPO_SETUP_FILE=${REPO_SETUP_FILE:-}"
} > "$OUT_ABS/dotnet_targeting.txt" || true

: "${DOTNET_TEST_TIMEOUT:=20m}"

# -----------------------------------------------------------------------------
# Resolve workdir
# -----------------------------------------------------------------------------
RUN_ROOT="$WT_ROOT"
if [[ -n "${DOTNET_WORKDIR:-}" ]]; then
  if [[ ! -d "$WT_ROOT/$DOTNET_WORKDIR" ]]; then
    echo "DOTNET_WORKDIR '$DOTNET_WORKDIR' does not exist under repo root." >&2
    echo "2" > "$OUT_ABS/dotnet_test_exit_code.txt"
    echo "${DOTNET_WORKDIR}" > "$OUT_ABS/test_workdir.txt" || true
    echo "${DOTNET_TEST_TARGET}" > "$OUT_ABS/test_target.txt" || true
    echo "" > "$OUT_ABS/test_strategy.txt" || true
    exit 2
  fi
  RUN_ROOT="$WT_ROOT/$DOTNET_WORKDIR"
fi

cd "$RUN_ROOT"
echo "${DOTNET_WORKDIR:-}" > "$OUT_ABS/test_workdir.txt" || true
echo "${DOTNET_TEST_TARGET:-}" > "$OUT_ABS/test_target.txt" || true

# -----------------------------------------------------------------------------
# Output dirs
# -----------------------------------------------------------------------------
TEST_LOG="$OUT_ABS/dotnet_test.log"
TEST_RC_FILE="$OUT_ABS/dotnet_test_exit_code.txt"
TRX_DIR="$OUT_ABS/test_results"
SARIF_DIR="$OUT_ABS/sarif"
mkdir -p "$TRX_DIR" "$SARIF_DIR"

# -----------------------------------------------------------------------------
# SARIF injection WITHOUT touching repo files (per-project + TFM + Configuration)
# -----------------------------------------------------------------------------
QC_SARIF_TARGETS="$OUT_ABS/qc.sarif.targets"

cat > "$QC_SARIF_TARGETS" <<'XML'
<Project>
  <PropertyGroup Condition="'$(QC_SARIF_DIR)' != ''">
    <_QCTfm Condition="'$(TargetFramework)' != ''">$(TargetFramework)</_QCTfm>
    <_QCTfm Condition="'$(TargetFramework)' == ''">default</_QCTfm>

    <_QCConf Condition="'$(Configuration)' != ''">$(Configuration)</_QCConf>
    <_QCConf Condition="'$(Configuration)' == ''">default</_QCConf>

    <!-- One SARIF per project + TFM + Configuration -->
    <ErrorLog>$(QC_SARIF_DIR)\$(MSBuildProjectName)_$(_QCTfm)_$(_QCConf).sarif,version=2.1</ErrorLog>
  </PropertyGroup>

  <Target Name="QCEnsureSarifDir" BeforeTargets="CoreCompile" Condition="'$(QC_SARIF_DIR)' != ''">
    <MakeDir Directories="$(QC_SARIF_DIR)" />
  </Target>
</Project>
XML

# -----------------------------------------------------------------------------
# Lizard complexity
# -----------------------------------------------------------------------------
LIZARD_DIR="$OUT_ABS/dotnet_complexity"
LIZARD_CSV="$LIZARD_DIR/lizard.csv"
mkdir -p "$LIZARD_DIR"

run_lizard() {
  echo "Running Lizard complexity: lizard --csv --languages csharp ." | tee -a "$TEST_LOG"
  (
    set +e
    timeout -k 30s "${LIZARD_TIMEOUT:-5m}" \
      lizard --csv --languages csharp . > "$LIZARD_CSV" 2>>"$TEST_LOG"
    exit 0
  ) || true
}

# -----------------------------------------------------------------------------
# Run dotnet test (single path)
# -----------------------------------------------------------------------------
DOTNET_TEST_ARGS=(test)
TEST_STRATEGY="workdir_only"
if [[ -n "${DOTNET_TEST_TARGET:-}" ]]; then
  DOTNET_TEST_ARGS+=( "${DOTNET_TEST_TARGET}" )
  TEST_STRATEGY="explicit_target"
fi

if [[ -n "${DOTNET_TEST_FILTER:-}" ]]; then
  DOTNET_TEST_ARGS+=( --filter "${DOTNET_TEST_FILTER}" )
fi
echo "$TEST_STRATEGY" > "$OUT_ABS/test_strategy.txt"

echo "Running: dotnet ${DOTNET_TEST_ARGS[*]} (workdir: $(pwd))" | tee "$TEST_LOG"

set +e
timeout -k 30s "$DOTNET_TEST_TIMEOUT" \
  dotnet "${DOTNET_TEST_ARGS[@]}" \
    --nologo \
    /p:CollectCoverage=false \
    /p:QC_SARIF_DIR="$SARIF_DIR" \
    /p:CustomAfterMicrosoftCommonTargets="$QC_SARIF_TARGETS" \
    --logger "trx" \
    --results-directory "$TRX_DIR" \
    2>&1 | tee -a "$TEST_LOG"
TEST_RC=${PIPESTATUS[0]}
set -e

echo "$TEST_RC" > "$TEST_RC_FILE"

# Always run complexity (must not affect pass/fail of tests)
run_lizard || true

if [[ $TEST_RC -ne 0 ]]; then
  echo "dotnet test failed with exit code $TEST_RC" >&2
  exit "$TEST_RC"
fi

echo "==> Collected artifacts in $OUT_ABS"