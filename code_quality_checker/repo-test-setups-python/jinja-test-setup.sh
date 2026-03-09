#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  default_install
  python -m pip install trio || true
}
