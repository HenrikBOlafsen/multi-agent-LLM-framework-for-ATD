#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run_all.sh PATH_TO_REPOS REPOS_TO_ANALYZE_FILE_PATH REFACTORING_ITERATION [OUTPUT_DIR] --openhands
# Example:
#   ./run_all.sh projects_to_analyze/ repos.txt 0 results/

PATH_TO_REPOS="${1%/}"
REPOS_TO_ANALYZE_FILE_PATH="${2%/}"
REFACTORING_ITERATION="${3%/}"
OUTPUT_DIR="${4:-results/}"

# For each repo in REPOS_TO_ANALYZE_FILE_PATH txt file (each row has "repo_name main_branch_name relative_src_path"): 
# Check if PATH_TO_REPOS already has the given repo inside
# If not, clone the repo
# If REFACTORING_ITERATION == 0:
# For each repo, make sure it is in the main_branch_name. If not, do git checkout
# Else:
# For each repo, make sure it is in the branch called cycle-fix-<REFACTORING_ITERATION>. If not, do git checkout


# === if not --openhands ===

# For each repo, run with branch_name as main_branch_name:
# run_pipeline.sh PATH_TO_REPOS/repo_name main_branch_name relative_src_path results/<repo_name>/<branch_name> --metrics-only 

# run_pipeline.sh PATH_TO_REPOS/repo_name branch_name relative_src_path results/<repo_name>/<branch_name> --explanation-only


# === if --openhands ===

# run_pipeline.sh PATH_TO_REPOS/repo_name branch_name relative_src_path results/<repo_name>/<branch_name> --openhands-only <new_branch_name>

