# repo-test-setups/alembic-test-setup.sh

# Optional: tweak installation (you can also skip this and just rely on default_install)
# QUALITY_INSTALL() {
#   echo "running alembic QUALITY_INSTALL()"
#   # Because Alembic already has a proper setup.cfg/pyproject, this might be enough:
#   python -m pip install -e .

#   # If Alembic has any testing extras or dev reqs, handle them here. Example:
#   if [[ -f "requirements-dev.txt" ]]; then
#     python -m pip install -r requirements-dev.txt || true
#   fi

#   # Common tooling (no xdist here – we'll disable it in QUALITY_TEST)
#   python -m pip install \
#     pytest pytest-cov pytest-timeout \
#     ruff mypy radon vulture bandit pip-audit
# }

QUALITY_INSTALL() {
  echo "running alembic QUALITY_INSTALL()"

  # Use the harness default (installs editable + pyproject extras + dependency-groups)
  default_install

  # Optional: if you want to ensure xdist never sneaks in from config,
  # we handle that in QUALITY_TEST anyway.
}


QUALITY_TEST() {
  echo "running alembic QUALITY_TEST()"
  export USE_PYTEST_XDIST=0
  default_pytest_run
}
