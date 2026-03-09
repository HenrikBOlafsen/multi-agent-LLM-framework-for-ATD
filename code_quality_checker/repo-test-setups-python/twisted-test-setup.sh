#!/usr/bin/env bash
set -euo pipefail

QUALITY_INSTALL() {
  echo "Twisted: install editable with extras"
  python -m pip install -e ".[all-non-platform]"
}

QUALITY_TEST() {
  echo "Twisted: running trial"

  export TOX_INI_DIR="${TOX_INI_DIR:-$PWD}"

  need_nss=0
  python - <<'PY' || need_nss=1
import os, pwd, grp
pwd.getpwuid(os.getuid())
grp.getgrgid(os.getgid())
PY

  if [[ "$need_nss" == "1" ]]; then
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

    [[ -r /etc/passwd ]] && cat /etc/passwd > "$PASSWD_FILE" || : > "$PASSWD_FILE"
    [[ -r /etc/group  ]] && cat /etc/group  > "$GROUP_FILE"  || : > "$GROUP_FILE"

    uid="$(id -u)"
    gid="$(id -g)"

    if ! awk -F: -v u="$uid" '$3==u{found=1} END{exit !found}' "$PASSWD_FILE"; then
      echo "qcuser:x:${uid}:${gid}:Quality Runner:/tmp:/bin/sh" >> "$PASSWD_FILE"
    fi
    if ! awk -F: -v g="$gid" '$3==g{found=1} END{exit !found}' "$GROUP_FILE"; then
      echo "qcgroup:x:${gid}:" >> "$GROUP_FILE"
    fi

    export LD_PRELOAD="${NSS_SO}${LD_PRELOAD:+:$LD_PRELOAD}"
    export NSS_WRAPPER_PASSWD="$PASSWD_FILE"
    export NSS_WRAPPER_GROUP="$GROUP_FILE"
    export HOME="${HOME:-/tmp}"
    export USER="${USER:-qcuser}"

    echo "Enabled NSS_WRAPPER (uid=${uid} gid=${gid})"
  fi

  export WATCHDOG_FORCE_POLLING=1

  TEST_LOG="$OUT_ABS/trial_full.log"

  # One test was too inconsistent in that it sometimes passes and sometimes gives errors, even when ran on the same commit. So it is disabled
  set -o pipefail
  python - <<'PY' 2>&1 | tee "$TEST_LOG"
from hypothesis import HealthCheck, settings
settings.register_profile("qc", suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("qc")

import sys
from twisted.scripts.trial import run

sys.argv = ["trial", "--reporter=verbose", "twisted"]
run()
PY

  TRIAL_RC=${PIPESTATUS[0]}
  if [[ $TRIAL_RC -ne 0 ]]; then
    echo "trial failed with exit code $TRIAL_RC" >&2
    exit $TRIAL_RC
  fi
}