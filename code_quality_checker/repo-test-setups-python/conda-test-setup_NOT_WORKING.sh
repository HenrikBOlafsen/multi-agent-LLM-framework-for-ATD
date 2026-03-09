#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "conda: minimal pip-only install"

  python -m pip install -U pip wheel setuptools
  python -m pip install -e . --no-deps

  python -m pip install \
    "archspec>=0.2.3" \
    "boltons>=23.0.0" \
    "charset-normalizer" \
    "conda-package-handling>=2.2.0" \
    "distro>=1.5.0" \
    "frozendict>=2.4.2" \
    "jsonpatch>=1.32" \
    "packaging>=23.0" \
    "platformdirs>=3.10.0" \
    "pluggy>=1.0.0" \
    "requests>=2.28.0,<3" \
    "ruamel.yaml>=0.11.14,<0.19" \
    "tqdm>=4" \
    "truststore>=0.8.0" \
    "zstandard>=0.15"

  python -m pip install "pycosat>=0.6.3" || true

  # menuinst stub (still needed)
  python - <<'PY'
import site
from pathlib import Path
sp = Path(site.getsitepackages()[0])
pkg = sp / "menuinst"
pkg.mkdir(exist_ok=True)
init = pkg / "__init__.py"
if not init.exists():
    init.write_text("__all__ = []\n__version__ = '0'\n")
print("Wrote stub:", init)
PY

  # Pytest + plugins + missing deps from your log
  python -m pip install \
    pytest pytest-cov pytest-timeout pytest-split pytest-xprocess \
    flask pytest-mock PyYAML pexpect responses \
    flaky
}

QUALITY_TEST() {
  export USE_PYTEST_XDIST=0
  # IMPORTANT: do NOT override markers=... (it wipes conda’s marker list)
  default_pytest_run
}

