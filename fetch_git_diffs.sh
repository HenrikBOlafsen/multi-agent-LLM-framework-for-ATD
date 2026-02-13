#!/usr/bin/env bash
set -euo pipefail

# Fetch git diffs for all refactoring branches in *every experiment* under RESULTS_ROOT.
# Layout assumed:
#   RESULTS_ROOT/<experiment>/<repo>/<branch>/openhands/status.json
#
# It writes (redacted):
#   - openhands/diff.patch
#   - openhands/diff.stats.txt
#
# Usage:
#   ./fetch_git_diffs.sh RESULTS_ROOT PROJECTS_DIR REPOS_FILE [--clone-missing]
#
#   RESULTS_ROOT : e.g., all_experiment_results
#   PROJECTS_DIR : directory for local clones (PROJECTS_DIR/<repo>)
#   REPOS_FILE   : "repos.txt" with lines: <repo_name> <main_branch> <src_rel_path>
#   --clone-missing : optionally clone missing repos using slug in status.json
#
# Requirements: git, python3

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 RESULTS_ROOT PROJECTS_DIR REPOs_FILE [--clone-missing]" >&2
  exit 2
fi

RESULTS_ROOT="${1%/}"
PROJECTS_DIR="${2%/}"
REPOS_FILE="$3"
CLONE_MISSING=0
if [[ "${4:-}" == "--clone-missing" ]]; then
  CLONE_MISSING=1
fi

need () { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 3; }; }
need git
need python3

[[ -d "$RESULTS_ROOT" ]] || { echo "Results root not found: $RESULTS_ROOT" >&2; exit 4; }
[[ -f "$REPOS_FILE"   ]] || { echo "Repos file not found: $REPOS_FILE" >&2; exit 5; }
mkdir -p "$PROJECTS_DIR"

# Map repo -> main branch
declare -A MAIN_BRANCH_OF
while read -r REPO_NAME MAIN_BRANCH SRC_REL || [[ -n "${REPO_NAME:-}" ]]; do
  [[ -z "${REPO_NAME:-}" || "$REPO_NAME" =~ ^# ]] && continue
  MAIN_BRANCH_OF["$REPO_NAME"]="$MAIN_BRANCH"
done < "$REPOS_FILE"

# ---- helpers ----
json_get () {
  local f="$1"; shift
  local key="$1"
  python3 - "$f" "$key" <<'PY'
import json, sys, pathlib
p=pathlib.Path(sys.argv[1])
k=sys.argv[2]
try:
    obj=json.loads(p.read_text(encoding='utf-8'))
    v=obj
    for part in k.split('.'):
        if isinstance(v, dict) and part in v: v=v[part]
        else: v=None; break
    print("" if v is None else v)
except Exception:
    print("")
PY
}

sanitize_file () {
  local file="$1"
  local owner="${2:-}"
  python3 - "$file" "$owner" <<'PY'
import re, sys, pathlib
path = pathlib.Path(sys.argv[1]); owner = sys.argv[2]
try:
    text = path.read_text(encoding='utf-8', errors='ignore')
except Exception:
    sys.exit(0)
text = re.sub(r'(github\.com/)[^/\s]+(/)', r'\1<redacted>\2', text)
text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '<redacted-email>', text)
if owner:
    text = re.sub(re.escape(owner), '<redacted-owner>', text)
path.write_text(text, encoding='utf-8')
PY
}
# -----------------

echo "Scanning experiments under: $RESULTS_ROOT"

# Iterate experiments
find "$RESULTS_ROOT" -mindepth 1 -maxdepth 1 -type d | while read -r EXP_DIR; do
  EXP_NAME="$(basename "$EXP_DIR")"
  echo
  echo "===== Experiment: $EXP_NAME ====="

  # Iterate repos inside this experiment
  find "$EXP_DIR" -mindepth 1 -maxdepth 1 -type d | while read -r REPO_RESULTS_DIR; do
    REPO="$(basename "$REPO_RESULTS_DIR")"
    MAIN_BRANCH="${MAIN_BRANCH_OF[$REPO]:-}"

    if [[ -z "$MAIN_BRANCH" ]]; then
      echo "  • Skipping folder '$REPO' (not listed in repos.txt as a repo)"
      continue
    fi

    echo "  --- Repo: $REPO (main=$MAIN_BRANCH) ---"
    LOCAL_REPO_DIR="$PROJECTS_DIR/$REPO"

    # Iterate branches within this repo for this experiment
    find "$REPO_RESULTS_DIR" -mindepth 1 -maxdepth 1 -type d | while read -r BRANCH_DIR; do
      BRANCH_NAME="$(basename "$BRANCH_DIR")"
      if [[ "$BRANCH_NAME" == "$MAIN_BRANCH" ]]; then
        echo "    • Skip main branch folder: $BRANCH_NAME"
        continue
      fi

      OH_DIR="$BRANCH_DIR/openhands"
      STATUS_JSON="$OH_DIR/status.json"
      if [[ ! -f "$STATUS_JSON" ]]; then
        echo "    • No openhands/status.json for $REPO/$BRANCH_NAME — skipping"
        continue
      fi

      PUSHED="$(json_get "$STATUS_JSON" pushed)"
      BASE_BRANCH="$(json_get "$STATUS_JSON" base_branch)"
      NEW_BRANCH="$(json_get "$STATUS_JSON" new_branch)"
      REPO_SLUG="$(json_get "$STATUS_JSON" repo)"  # owner/repo, used for cloning + redaction

      if [[ -z "$BASE_BRANCH" || -z "$NEW_BRANCH" ]]; then
        echo "    • status.json missing base/new branch info — skipping"
        continue
      fi

      if [[ "$PUSHED" != "True" && "$PUSHED" != "true" ]]; then
        echo "    • $REPO/$BRANCH_NAME not pushed (pushed=$PUSHED) — skipping diff"
        echo "not_pushed=true" > "$OH_DIR/diff.skip.txt"
        continue
      fi

      GH_OWNER=""
      if [[ -n "$REPO_SLUG" && "$REPO_SLUG" == */* ]]; then
        GH_OWNER="${REPO_SLUG%%/*}"
      fi

      if [[ ! -d "$LOCAL_REPO_DIR/.git" ]]; then
        if [[ $CLONE_MISSING -eq 1 ]]; then
          if [[ -z "$REPO_SLUG" ]]; then
            echo "    • Cannot clone '$REPO' (no slug in status.json). Skipping."
            continue
          fi
          echo "    • Cloning remote repo → $LOCAL_REPO_DIR"
          git clone "https://github.com/${REPO_SLUG}.git" "$LOCAL_REPO_DIR" >/dev/null 2>&1 || {
            echo "      - Clone failed (maybe private?). Skipping."
            continue
          }
        else
          echo "    • Local repo missing: $LOCAL_REPO_DIR — use --clone-missing. Skipping."
          continue
        fi
      fi

      echo "    • Diffing origin/$BASE_BRANCH..origin/$NEW_BRANCH → $OH_DIR/diff.patch"
      set +e
      git -C "$LOCAL_REPO_DIR" fetch origin "$BASE_BRANCH" "$NEW_BRANCH" --prune >/dev/null 2>&1
      FETCH_STATUS=$?
      set -e
      if [[ $FETCH_STATUS -ne 0 ]]; then
        echo "      - fetch failed; skipping."
        continue
      fi

      DIFF_PATH="$OH_DIR/diff.patch"
      STATS_PATH="$OH_DIR/diff.stats.txt"
      set +e
      git -C "$LOCAL_REPO_DIR" diff --patience --binary --full-index "origin/$BASE_BRANCH..origin/$NEW_BRANCH" > "$DIFF_PATH"
      DIFF_EXIT=$?
      set -e
      if [[ $DIFF_EXIT -ne 0 || ! -s "$DIFF_PATH" ]]; then
        echo "      - diff empty or failed; writing note."
        echo "empty_or_failed=true" > "$OH_DIR/diff.empty.txt"
        continue
      fi
      git -C "$LOCAL_REPO_DIR" diff --shortstat "origin/$BASE_BRANCH..origin/$NEW_BRANCH" > "$STATS_PATH" || true

      # Redact any owner/username and email-like tokens
      sanitize_file "$DIFF_PATH"  "$GH_OWNER"
      sanitize_file "$STATS_PATH" "$GH_OWNER"

      echo "      - wrote (redacted): $(basename "$DIFF_PATH"), $(basename "$STATS_PATH")"
    done
  done
done

echo
echo "✅ Done collecting diffs across all experiments (owner info redacted)."
