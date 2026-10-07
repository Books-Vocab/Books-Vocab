#!/usr/bin/env bash
# ci_apt_install.sh — install apt packages on a hosted runner without letting a
# slow mirror turn into a bare exit 137 (issue #2167).
#
# Usage: ops/ci_apt_install.sh <package>...
#
# No packages -> exit 0 without touching apt. Otherwise up to 3 install
# attempts; between failed attempts: backoff, then a bounded `apt-get update`
# (a failed update is tolerated). Every apt-get call runs as
# `sudo timeout --kill-after=10s <N>s apt-get -o Acquire::Retries=3 ...` so the
# timeout runs as root and kills apt-get itself, not just the sudo wrapper
# (an orphaned apt-get would keep the dpkg lock and doom the next attempt).
#
# Worst-case wall clock, all attempts failing by timeout:
#   3 x (120s + 10s)   installs
# + 2 x (45s + 10s)    updates between attempts
# + 5s + 10s           backoff
# = 515s (< 8.6 min), inside the 20 min shard timeout.
set -euo pipefail

case "${1:-}" in
  -h|--help)
    awk 'NR>1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"
    exit 0
    ;;
esac

(( $# > 0 )) || exit 0

attempts=3
install_timeout=120
update_timeout=45
kill_after=10
packages=("$@")

run_apt() {  # apt <duration-seconds> <apt-get args...>
  local seconds="$1"; shift
  sudo timeout --kill-after="${kill_after}s" "${seconds}s" \
    apt-get -o Acquire::Retries=3 -o DPkg::Lock::Timeout=30 "$@"
}

rc=0
for (( attempt = 1; attempt <= attempts; attempt++ )); do
  rc=0
  run_apt "$install_timeout" install -y --no-install-recommends "${packages[@]}" || rc=$?
  if (( rc == 0 )); then
    exit 0
  fi
  echo "::warning::apt-get install attempt ${attempt}/${attempts} failed (exit ${rc}; 124/137 = timed out): ${packages[*]}" >&2
  if (( attempt < attempts )); then
    sleep $(( attempt * 5 ))
    run_apt "$update_timeout" update || echo "::warning::apt-get update failed or timed out; retrying install anyway" >&2
  fi
done

echo "::error::apt-get install failed after ${attempts} attempts (last exit ${rc}): ${packages[*]}" >&2
exit 1
