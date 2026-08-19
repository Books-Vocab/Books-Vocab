#!/usr/bin/env bash
# Keep the hosted-Linux shard bootstrap narrow, fail-closed, and bounded.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/ops-suite.yml"

failures=0
fail() {
  printf '✗ %s\n' "$1" >&2
  failures=$((failures + 1))
}

bootstrap="$(
  awk '
    /^      - name: Verify tools the shard needs$/ { in_step=1; next }
    in_step && /^      - name: / { exit }
    in_step { print }
  ' "$WORKFLOW"
)"

if [[ -z "$bootstrap" ]]; then
  fail "ops-suite has no Linux shard tool-bootstrap step"
fi

require_bootstrap_literal() {
  local needle="$1"
  local description="$2"
  if ! grep -Fq -- "$needle" <<<"$bootstrap"; then
    fail "$description"
  fi
}

require_bootstrap_literal 'set -euo pipefail' "tool-bootstrap is not fail-closed"
require_bootstrap_literal 'declare -A packages=(' "tool-bootstrap has no explicit tool package map"
for mapping in '[rg]=ripgrep' '[jq]=jq' '[sqlite3]=sqlite3' '[python3]=python3' '[ssh]=openssh-client' '[zsh]=zsh'; do
  require_bootstrap_literal "$mapping" "tool-bootstrap omits explicit map entry: $mapping"
done
require_bootstrap_literal 'missing=()' "tool-bootstrap does not collect missing packages"
require_bootstrap_literal 'command -v "$command_name" >/dev/null 2>&1 || missing+=("${packages[$command_name]}")' "tool-bootstrap does not map missing commands to explicit packages"

if grep -Eq '(^|[[:space:]])apt(-get)?[[:space:]]+update' <<<"$bootstrap"; then
  fail "tool-bootstrap adds an unbounded apt update"
fi

bounded_install='timeout --signal=KILL 180s sudo apt-get install -y --no-install-recommends "${missing[@]}"'
require_bootstrap_literal "$bounded_install" "missing-tool provisioning is not hard-bounded to 180 seconds"

install_count="$(grep -Ec 'apt-get[[:space:]]+install' <<<"$bootstrap" || true)"
if [[ "$install_count" != 1 ]]; then
  fail "tool-bootstrap has broad or duplicate apt package installation"
fi

post_install_check='command -v "$command_name" >/dev/null 2>&1'
if ! awk -v bounded_install="$bounded_install" -v post_install_check="$post_install_check" '
  index($0, bounded_install) { provisioned=1; next }
  provisioned && index($0, post_install_check) { verified=1 }
  END { exit !verified }
' <<<"$bootstrap"; then
  fail "tool-bootstrap does not fail closed after bounded provisioning"
fi

if ! grep -Fq '      - name: Run assigned Linux ops groups' "$WORKFLOW"; then
  fail "ops-suite no longer runs assigned Linux groups after tool verification"
fi
if ! grep -Fq './ops/test_ops.sh "${selected[@]}"' "$WORKFLOW"; then
  fail "ops-suite no longer executes the assigned Linux groups"
fi

if (( failures > 0 )); then
  printf 'ops-suite bootstrap contract: %d failure(s)\n' "$failures" >&2
  exit 1
fi
printf 'ops-suite bootstrap contract: PASS\n'
