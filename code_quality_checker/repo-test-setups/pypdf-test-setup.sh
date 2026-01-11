#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "pypdf: install project + test deps"

  python -m pip install -e ".[full,dev]" \
    || python -m pip install -e ".[dev]" \
    || python -m pip install -e .

  # provides --enable-socket / --disable-socket
  python -m pip install -U pytest-socket

  # many image tests need Pillow
  python -m pip install -U Pillow || true
}

QUALITY_TEST() {
  echo "pypdf: ensure sample files exist"

  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git submodule sync -q || true
    git submodule update --init --recursive || true
  fi
  if [[ ! -d "sample-files" ]]; then
    git clone --depth 1 https://github.com/py-pdf/sample-files.git sample-files
  fi

  export USE_PYTEST_XDIST=0

  # IMPORTANT:
  # 1) Don't export this (prevents pytest auto-injecting it)
  # 2) Use --force-enable-socket to override config's --disable-socket
  PYTEST_ADDOPTS="-o addopts= --force-enable-socket"

  default_pytest_run
}

