# repo-test-setups/alembic-test-setup.sh

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
