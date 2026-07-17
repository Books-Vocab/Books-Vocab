#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT_DIR="$ROOT/ops"
secret='super-secret-review-token'
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# shellcheck source=../lib/ios_ops_core.sh
source "$ROOT/ops/lib/ios_ops_core.sh"

KG_IOS_OPS_HEARTBEAT_INTERVAL=0.02 \
  ios_ops_stream_capture release-fixture \
    python3 -c 'import sys,time; time.sleep(0.08); print("{\"status\":\"pass\"}")' \
    "$secret" >"$tmp/stdout" 2>"$tmp/stderr"

jq -e '.status == "pass"' "$tmp/stdout" >/dev/null
[[ "$(wc -l <"$tmp/stdout" | tr -d ' ')" == "1" ]]
grep -qE 'source=release-fixture phase=start elapsed=0\.0s pid=not-spawned alive=false argCount=[0-9]+' "$tmp/stderr"
grep -qE 'source=release-fixture phase=spawned elapsed=[0-9.]+s pid=[0-9]+ alive=true' "$tmp/stderr"
grep -qE 'source=release-fixture phase=heartbeat elapsed=[0-9.]+s pid=[0-9]+ alive=true' "$tmp/stderr"
grep -qE 'source=release-fixture phase=done elapsed=[0-9.]+s pid=[0-9]+ alive=false rc=0' "$tmp/stderr"
if grep -qF "$secret" "$tmp/stderr"; then
  echo "raw argv leaked to progress stderr" >&2
  exit 1
fi

fixture="$tmp/sources"
mkdir -p "$fixture"
cat >"$fixture/project-settings.stdout" <<'EOF'
    MARKETING_VERSION = 2.0.1
    CURRENT_PROJECT_VERSION = 7
EOF
printf '2026-07-17T00:00:00Z\tBooksAndVocab\tcom.Max0228.BooksBrowser\t2.0.1\t7\t/tmp/fixture.xcarchive\n' >"$fixture/organizer-latest.stdout"
printf '6\n' >"$fixture/testflight-builds.stdout"
printf '2.0.1 PREPARE_FOR_SUBMISSION\n' >"$fixture/asc-versions.stdout"
printf '{"verdict":{"status":"pass","blockCount":0},"blocks":[]}\n' >"$fixture/app-review-gate.stdout"

KG_IOS_OPS_FIXTURE=1 \
KG_IOS_OPS_RELEASE_SOURCE_FIXTURE_DIR="$fixture" \
KG_IOS_OPS_RELEASE_SOURCE_FIXTURE_DELAY=0.08 \
KG_IOS_OPS_RELEASE_SOURCE_SECRET_FIXTURE="$secret" \
KG_IOS_OPS_HEARTBEAT_INTERVAL=0.02 \
  bash "$ROOT/ops/ios_ops.sh" workflow release --json \
  >"$tmp/workflow.json" 2>"$tmp/workflow.stderr"

jq -e -s 'length == 1 and .[0].schema == "kg.ios.workflow.v1"' "$tmp/workflow.json" >/dev/null
for label in project-settings organizer-latest testflight-builds asc-versions app-review-gate; do
  for phase in start spawned heartbeat done; do
    grep -q "source=workflow-$label phase=$phase" "$tmp/workflow.stderr"
  done
done
if grep -qF "$secret" "$tmp/workflow.stderr"; then
  echo "workflow progress leaked raw argv" >&2
  exit 1
fi
sort "$fixture/invocations.log" >"$tmp/invocations.sorted"
printf '%s\n' app-review-gate asc-versions organizer-latest project-settings testflight-builds >"$tmp/expected-invocations"
cmp "$tmp/expected-invocations" "$tmp/invocations.sorted"
if grep -Eq '^(build|upload|write|set-|submit)' "$fixture/invocations.log"; then
  echo "workflow fixture observed a mutating invocation" >&2
  exit 1
fi

# A provider failure remains structured, and ASC timeout exits 124 without
# corrupting workflow JSON or silently falling back to a mutation.
printf '9\n' >"$fixture/project-settings.rc"
KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_RELEASE_SOURCE_FIXTURE_DIR="$fixture" \
KG_IOS_OPS_HEARTBEAT_INTERVAL=0.02 \
  bash "$ROOT/ops/ios_ops.sh" workflow release --json \
  >"$tmp/nonzero.json" 2>"$tmp/nonzero.stderr"
jq -e '.schema == "kg.ios.workflow.v1" and .version == "unknown"' "$tmp/nonzero.json" >/dev/null
grep -q 'source=workflow-project-settings phase=done .* rc=9' "$tmp/nonzero.stderr"
rm "$fixture/project-settings.rc"

printf '0.2\n' >"$fixture/asc-versions.delay"
KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_RELEASE_SOURCE_FIXTURE_DIR="$fixture" \
KG_IOS_OPS_ASC_TIMEOUT_SECONDS=0.05 KG_IOS_OPS_HEARTBEAT_INTERVAL=0.02 \
  bash "$ROOT/ops/ios_ops.sh" workflow release --json \
  >"$tmp/timeout.json" 2>"$tmp/timeout.stderr"
jq -e '.schema == "kg.ios.workflow.v1" and any(.steps[]; .key == "asc-review" and .status == "warn")' "$tmp/timeout.json" >/dev/null
grep -q 'source=workflow-asc-versions phase=done .* rc=124' "$tmp/timeout.stderr"

echo "ios ops release heartbeat contract: PASS"
