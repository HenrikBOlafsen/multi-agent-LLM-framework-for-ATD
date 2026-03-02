#!/usr/bin/env bash
# repo-test-setups/twisted-test-setup.sh
#
# Minimal, close-to-normal Twisted run in a container:
# - install editable with Twisted extras used by CI-ish runs
# - set TOX_INI_DIR so "examples" tests can locate the repo root
# - if uid/gid aren't resolvable via pwd/grp (common with docker --user),
#   enable NSS_WRAPPER via LD_PRELOAD using a tiny passwd/group overlay
#
# NOTE: We intentionally do NOT suppress Hypothesis health checks.
#       If a Hypothesis too_slow health check fails, we keep that failure.

set -euo pipefail

QUALITY_INSTALL() {
  echo "Twisted: install editable with extras"
  python -m pip install -e ".[all-non-platform]"
}

QUALITY_TEST() {
  echo "Twisted: running trial"

  # Some Twisted tests expect this when run under tox; setting it here makes
  # them behave like a "repo-root aware" run without actually using tox.
  export TOX_INI_DIR="${TOX_INI_DIR:-$PWD}"

  # If the container runs with --user UID:GID that doesn't exist in /etc/passwd
  # and /etc/group, Python's pwd/grp (and getpass.getuser()) can fail.
  need_nss=0
  python - <<'PY' || need_nss=1
import os, pwd, grp
pwd.getpwuid(os.getuid())
grp.getgrgid(os.getgid())
PY

  if [[ "$need_nss" == "1" ]]; then
    # Find libnss_wrapper.so in common Debian multiarch paths.
    NSS_SO=""
    for p in \
      /usr/lib/*/libnss_wrapper.so \
      /usr/lib/libnss_wrapper.so \
      /lib/*/libnss_wrapper.so \
      /lib/libnss_wrapper.so
    do
      if [[ -r "$p" ]]; then
        NSS_SO="$p"
        break
      fi
    done

    if [[ -z "$NSS_SO" ]]; then
      echo "ERROR: uid/gid not resolvable and libnss-wrapper is missing." >&2
      echo "       Install Debian package: libnss-wrapper" >&2
      exit 2
    fi

    NSS_DIR="$(mktemp -d)"
    trap 'rm -rf "$NSS_DIR" 2>/dev/null || true' EXIT

    PASSWD_FILE="$NSS_DIR/passwd"
    GROUP_FILE="$NSS_DIR/group"

    # Seed from system files if readable, then append minimal entries.
    if [[ -r /etc/passwd ]]; then cat /etc/passwd > "$PASSWD_FILE"; else : > "$PASSWD_FILE"; fi
    if [[ -r /etc/group  ]]; then cat /etc/group  > "$GROUP_FILE";  else : > "$GROUP_FILE";  fi

    uid="$(id -u)"
    gid="$(id -g)"

    # Add entries only if missing.
    if ! awk -F: -v u="$uid" '$3==u{found=1} END{exit !found}' "$PASSWD_FILE"; then
      echo "qcuser:x:${uid}:${gid}:Quality Runner:/tmp:/bin/sh" >> "$PASSWD_FILE"
    fi
    if ! awk -F: -v g="$gid" '$3==g{found=1} END{exit !found}' "$GROUP_FILE"; then
      echo "qcgroup:x:${gid}:" >> "$GROUP_FILE"
    fi

    export LD_PRELOAD="${NSS_SO}${LD_PRELOAD:+:$LD_PRELOAD}"
    export NSS_WRAPPER_PASSWD="$PASSWD_FILE"
    export NSS_WRAPPER_GROUP="$GROUP_FILE"

    # Helps getpass.getuser() and similar calls pick a stable value
    export HOME="${HOME:-/tmp}"
    export USER="${USER:-qcuser}"

    echo "Enabled NSS_WRAPPER (uid=${uid} gid=${gid})"
  fi

  export WATCHDOG_FORCE_POLLING=1

  # Keep it close to normal: just run Twisted's own runner over the package.
  TEST_LOG="${OUT_ABS:-$PWD}/trial_full.log"
  set -o pipefail
  python -m twisted.trial --reporter=verbose twisted 2>&1 | tee "$TEST_LOG"
}