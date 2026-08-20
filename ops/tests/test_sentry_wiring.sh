#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OPS="$ROOT/ops/ios_ops.sh"
PASS=0
FAIL=0

ok() { PASS=$((PASS + 1)); echo "✓ $1"; }
fail() { FAIL=$((FAIL + 1)); echo "✗ $1" >&2; }

summary() {
  KG_IOS_SENTRY_BUILD_LOCK_TIMEOUT=0 \
    KG_IOS_OPS_SENTRY_BUILD_CAN_IMPORT_FIXTURE=true \
    KG_IOS_OPS_SENTRY_API_AUTHENTICATED_FIXTURE=true \
    KG_IOS_OPS_SENTRY_PROJECT_REACHABLE_FIXTURE=true \
    KG_IOS_OPS_SENTRY_RUNTIME_EVENT_FIXTURE=true \
    KG_IOS_OPS_SENTRY_SYMBOLICATION_FIXTURE=true \
    SENTRY_API_URL=https://sentry.example.test SENTRY_AUTH_TOKEN=fixture-token \
    SENTRY_ORG=kg-org SENTRY_PROJECT_IOS=ios \
    bash "$OPS" sentry --json
}

healthy="$(summary)"
if jq -e '.verdict == "ready" and .wiring.packagePresent and .wiring.targetLinked and .readiness.build_can_import == true and .readiness.api_configured' <<<"$healthy" >/dev/null; then
  ok "healthy static/API fixture reaches ready"
else
  fail "healthy fixture did not reach ready: $healthy"
fi

package_blocked="$(KG_IOS_SENTRY_BUILD_LOCK_TIMEOUT=0 KG_IOS_OPS_SENTRY_PACKAGE_FIXTURE=0 bash "$OPS" sentry --json)"
if jq -e '.verdict == "blocked" and any(.issues[]; .key == "package")' <<<"$package_blocked" >/dev/null; then
  ok "missing package is blocked"
else
  fail "missing package did not block: $package_blocked"
fi

target_blocked="$(KG_IOS_SENTRY_BUILD_LOCK_TIMEOUT=0 KG_IOS_OPS_SENTRY_TARGET_FIXTURE=0 bash "$OPS" sentry --json)"
if jq -e '.verdict == "blocked" and any(.issues[]; .key == "targetLinked")' <<<"$target_blocked" >/dev/null; then
  ok "missing app-target link is blocked"
else
  fail "missing target link did not block: $target_blocked"
fi

build_blocked="$(KG_IOS_OPS_SENTRY_BUILD_CAN_IMPORT_FIXTURE=false KG_IOS_SENTRY_BUILD_LOCK_TIMEOUT=0 bash "$OPS" sentry --json)"
if jq -e '.verdict == "blocked" and any(.issues[]; .key == "buildCanImport")' <<<"$build_blocked" >/dev/null; then
  ok "negative build import evidence is blocked"
else
  fail "negative build evidence did not block: $build_blocked"
fi

missing_dsn="$(tmp_plist="$(mktemp)"; cp "$ROOT/ios/Info.plist" "$tmp_plist"; plutil -remove SentryDSN "$tmp_plist"; KG_IOS_SENTRY_BUILD_LOCK_TIMEOUT=0 KG_IOS_OPS_SENTRY_INFO_PLIST_FIXTURE="$tmp_plist" bash "$OPS" sentry --json; rm -f "$tmp_plist")"
if jq -e '.wiring.dsnKeyReference == false and any(.issues[]; .key == "dsnKeyReference")' <<<"$missing_dsn" >/dev/null; then
  ok "app target Info.plist is the DSN source of truth"
else
  fail "missing target DSN was false-green: $missing_dsn"
fi

partial_doctor="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_SENTRY_BUILD_CAN_IMPORT_FIXTURE=true KG_IOS_SENTRY_BUILD_LOCK_TIMEOUT=0 bash "$OPS" doctor --json)"
if jq -e 'any(.readiness[]; .key == "sentry" and .status == "warn" and (.detail | contains("verdict=partial")))' <<<"$partial_doctor" >/dev/null; then
  ok "partial Sentry readiness is not doctor-ok"
else
  fail "partial Sentry readiness was doctor-ok: $partial_doctor"
fi

lock_file="$(mktemp)"
rm -f "$lock_file"
shlock -f "$lock_file" -p "$$"
locked="$(KG_IOS_BUILD_LOCK_FILE="$lock_file" KG_IOS_SENTRY_BUILD_LOCK_TIMEOUT=0 bash "$OPS" sentry --json)"
rm -f "$lock_file"
if jq -e '.build_evidence.source == "build-lock-unavailable" and .readiness.build_can_import == "unchecked"' <<<"$locked" >/dev/null; then
  ok "build evidence refuses an unlocked shared-cache read"
else
  fail "build evidence ignored the shared build lock: $locked"
fi

echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
