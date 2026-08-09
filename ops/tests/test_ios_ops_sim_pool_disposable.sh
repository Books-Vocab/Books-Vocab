#!/usr/bin/env bash
# test_ios_ops_sim_pool_disposable.sh — the pool-lease disposability guard
# (IMP-20260806-06d033). Offline, no simulator, no Xcode.
#
# WHAT THE GUARD IS FOR
# kg-pool-2 (14A23ED5) is signed into a REAL Apple account (000287.04e2…) and
# its LocalStore holds 9,580 genuine ReviewRecords. `ios_test.sh --ui` leases
# pool simulators as disposable resources, and UI-test fixtures have wiped an
# app container before (memory: uitest-fixture-device-store-wipe). Nothing
# stopped a lease from handing that device to a fixture. The guard reads the
# app's KGUserId before the slot is used and refuses anything that is not
# provably a test identity.
#
# WHICH ASSERTION PROVES WHAT (each names the fake fix it kills):
#   * A3 kills "no guard at all".
#   * A6 kills a BLACKLIST (`[[ $id == 000287.* ]]`). A blacklist passes A3 and
#     still hands over every account whose prefix nobody thought of. The guard's
#     contract is default-DENY: unknown identity = refuse.
#   * A7 kills a SUBSTRING match (`*kg-test*`), which would treat an Apple id
#     that merely contains the token as disposable.
#   * A5 pins the refusal onto stderr. `simulator lease` prints the UDID on
#     STDOUT and callers consume it as one — a diagnostic on stdout does not
#     just look untidy, it feeds a refusal string to `simctl` as a device id.
#   * A9 pins fail-safe aggregation: a device with several app containers can
#     yield several ids, and ONE real account among them is still a refusal.
#   * Section B kills "function written but never wired" — the specific false
#     green the ticket names. It greps a DIFFERENT function's body, so no
#     literal in section A can make it tautological. B2 additionally pins the
#     ORDER: the check must precede `simctl boot`, because booting the device
#     is already the act that lets a fixture attach to it.
#   * Section C kills the reader this ticket was originally planned with.
#     MEASURED 2026-08-08 on oscar, before any code was written:
#       `xcrun simctl spawn 14A23ED5 defaults read com.Max0228.BooksBrowser \
#          KGUserId`  ->  rc=149, "device is not booted"
#       `plutil -extract KGUserId raw -o - <container>/…/…BooksBrowser.plist`
#                      ->  000287.04e2540…   (device stayed Shutdown)
#     kg-pool-2 was Shutdown at the time — the normal state of a slot about to
#     be leased, since lease is what boots it. A spawn-only reader therefore
#     returns EMPTY for the one device this guard exists for, and empty reads
#     as disposable. C2 runs the reader with `xcrun` masked by an exit-127 stub
#     against a synthetic device tree: it must still find the id. A spawn-only
#     reader cannot pass that.
#
# HOW THE FUNCTIONS ARE LOADED
# Extracted with awk and sourced into a subshell, never by sourcing the whole
# lib — the same loading contract the ticket's acceptance_cmd uses, so the two
# cannot drift apart, and sourcing the lib's top level here would drag in its
# side effects.
#
# CI: registered as group `sim-pool-disposable` (ops/test_ops.sh) and listed in
# LINUX_GROUPS (ops/tests/test_ops_ci_coverage.sh). Sections A and B are pure
# bash/awk/grep and run on the linux runner. Section C needs `plutil`, which is
# macOS-only userland; where it is absent the section SKIPS LOUDLY and the
# summary reports the count. Read that as: CI guards the guard's logic and its
# wiring; the boot-independence of the reader is pinned on macOS only.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$WORKSPACE/ops/lib/ios_ops_simulator.sh"

pass=0; fail=0; skipped=0
ok()      { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t()  { echo "  ✗ $*"; fail=$((fail+1)); }
skip_t()  { echo "  ⊘ SKIP $*"; skipped=$((skipped+1)); }
section() { echo ""; echo "── $* ──"; }

[[ -f "$LIB" ]] || { echo "FATAL: $LIB missing"; exit 1; }

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# extract_fn <name> — the awk range used by the acceptance command. A function
# whose body carries a column-0 `}` would be truncated here, which is itself
# worth catching, so the extraction is not made cleverer than the acceptance.
extract_fn() {
  awk -v fn="^$1\\\\(\\\\)" '$0 ~ fn,/^}$/' "$LIB"
}

# ── A. the guard, as a pure function ─────────────────────────────────────────
# run_guard <name> <user_id> — sets G_RC / G_OUT / G_ERR.
run_guard() {
  local src="$TMP/guard.sh" out="$TMP/g.out" err="$TMP/g.err" rc=0
  : >"$out"; : >"$err"
  extract_fn simulator_pool_assert_disposable >"$src"
  bash -c 'set -uo pipefail; . "$1"; simulator_pool_assert_disposable "$2" "$3"' \
    _ "$src" "$1" "$2" >"$out" 2>"$err" || rc=$?
  G_RC="$rc"; G_OUT="$(cat "$out")"; G_ERR="$(cat "$err")"
}

expect_allow() { # <label> <name> <user_id>
  run_guard "$2" "$3"
  [[ "$G_RC" -eq 0 ]] && ok "$1: allowed (rc=0)" || fail_t "$1: rc=$G_RC, want 0 (err: ${G_ERR:-<empty>})"
}
expect_refuse() { # <label> <name> <user_id>
  run_guard "$2" "$3"
  # rc!=0 is NOT enough. With the function absent, bash exits 127 and every
  # negative control below goes green while proving nothing — measured on the
  # red run of this file: 6 spurious ✓. A refusal must come from the guard, so
  # it must not be 127 and must not carry bash's not-found diagnostic.
  if [[ "$G_RC" -eq 0 ]]; then
    fail_t "$1: rc=0 — a non-disposable account was ALLOWED"
  elif [[ "$G_RC" -eq 127 || "$G_ERR" == *"command not found"* ]]; then
    fail_t "$1: rc=$G_RC came from a MISSING function, not a refusal (${G_ERR:-<empty>})"
  else
    ok "$1: refused (rc=$G_RC)"
  fi
}

section "A. guard semantics (default-deny)"
bash -n "$LIB" && ok "A0 lib syntax" || fail_t "A0 lib syntax"

extract_fn simulator_pool_assert_disposable >"$TMP/probe.sh"
if [[ -s "$TMP/probe.sh" ]] && bash -c 'set -u; . "$1"; declare -F simulator_pool_assert_disposable >/dev/null' _ "$TMP/probe.sh"; then
  ok "A1 simulator_pool_assert_disposable is awk-extractable and loads standalone"
else
  fail_t "A1 simulator_pool_assert_disposable is not extractable/loadable — everything below is meaningless"
fi

# Positive controls. Without these, "always refuse" would be a green guard that
# makes the entire pool unleasable.
expect_allow  "A2 empty KGUserId (fresh sim)"        kg-pool-1 ""
expect_allow  "A2b test identity"                    kg-pool-3 "kg-test-8f21"
expect_allow  "A2c bare kg-test prefix"              kg-pool-3 "kg-test"

# Negative control: the real account this ticket was filed for.
expect_refuse "A3 the production Apple id on kg-pool-2" kg-pool-2 "000287.04e2f0228"

section "A. anti-fake-fix"
# A blacklist keyed on 000287.* passes A3 and fails here.
expect_refuse "A6 unknown identity (not a blacklist)"   kg-pool-4 "some-real-user-42"
expect_refuse "A6b another unknown shape"               kg-pool-4 "auth0|61f0c3"
# A substring match passes A2b and fails here.
expect_refuse "A7 kg-test present but not the prefix"   kg-pool-5 "000287.kg-test.04e2"
# Real readers hand back trailing whitespace/CR.
expect_refuse "A8 production id with trailing CR/space" kg-pool-2 "000287.04e2f0228 "
# Fail-safe aggregation over several app containers.
expect_refuse "A9 mixed set, one real account"          kg-pool-2 "kg-test-1
000287.04e2f0228"
expect_allow  "A9b all-disposable set"                  kg-pool-1 "kg-test-1
kg-test-2"
expect_allow  "A9c blank lines only"                    kg-pool-1 "

"

section "A. the two refusal modes are distinguishable"
# One dirty account blocks ONE slot; a blind detector blocks EVERY slot. The
# caller can only word those differently if the guard tells them apart, so the
# exit codes are part of the contract, not an implementation detail.
run_guard kg-pool-2 "000287.04e2f0228"
[[ "$G_RC" -eq 1 ]] \
  && ok "A10 a real identity refuses with rc=1" \
  || fail_t "A10 real identity gave rc=$G_RC, want 1"
run_guard kg-pool-3 "unverifiable:plutil-missing"
[[ "$G_RC" -eq 2 ]] \
  && ok "A11 an unverifiable read refuses with rc=2 (distinct from 1)" \
  || fail_t "A11 unverifiable gave rc=$G_RC, want 2 — caller cannot tell a pool-wide outage from one logged-in sim"
[[ "$G_ERR" == *"無法確認"* && "$G_ERR" != *"登著非拋棄帳號"* ]] \
  && ok "A11b the unverifiable message does not claim someone is logged in" \
  || fail_t "A11b unverifiable message misattributes the cause: ${G_ERR:-<empty>}"

section "A. diagnostics"
run_guard kg-pool-2 "000287.04e2f0228"
# The rc precondition matters: with the function deleted, stdout is empty too
# and this would applaud a guard that does not exist.
if [[ "$G_RC" -eq 127 ]]; then
  fail_t "A5 cannot judge stdout — the function is missing (rc=127)"
elif [[ -z "$G_OUT" ]]; then
  ok "A5 refusal wrote NOTHING to stdout (lease's stdout is the UDID)"
else
  fail_t "A5 refusal leaked to stdout: '$G_OUT' — callers consume that as a device id"
fi
[[ "$G_ERR" == *"refuse"* && "$G_ERR" == *"kg-pool-2"* ]] \
  && ok "A5b refusal names the device on stderr" \
  || fail_t "A5b stderr does not name the refusal + device (got: ${G_ERR:-<empty>})"
run_guard kg-pool-1 "kg-test-1"
[[ -z "$G_OUT$G_ERR" ]] \
  && ok "A5c the allow path is silent (no cry-wolf on every lease)" \
  || fail_t "A5c allow path printed: out='$G_OUT' err='$G_ERR'"

# ── B. wiring into cmd_simulator_lease ───────────────────────────────────────
section "B. cmd_simulator_lease actually calls it"
LEASE="$TMP/lease.sh"
# Comments are stripped FIRST. Grepping the raw body counts a commented-out
# call as wiring — measured: prefix the four call lines with `#` and B1-B4 all
# stay green, which is exactly how this wiring dies in practice. Same `sed` and
# same reason as ops/tests/test_ops_ci_coverage.sh's run_one probe. Lines are
# blanked, not deleted, so the ordering assertion below keeps its line numbers.
extract_fn cmd_simulator_lease | sed 's/[[:space:]]*#.*$//' >"$LEASE"
[[ -s "$LEASE" ]] && ok "B0 cmd_simulator_lease body extracted (comments stripped)" || fail_t "B0 could not extract cmd_simulator_lease"

grep -q 'simulator_pool_assert_disposable' "$LEASE" \
  && ok "B1 the lease path invokes the guard" \
  || fail_t "B1 the guard is never called from cmd_simulator_lease — written but unwired"

# Order: guard AFTER the udid is resolved, BEFORE the device is booted.
ln_udid="$(grep -n 'simulator_pool_ensure_device' "$LEASE" | head -1 | cut -d: -f1 || true)"
ln_guard="$(grep -n 'simulator_pool_assert_disposable' "$LEASE" | head -1 | cut -d: -f1 || true)"
ln_boot="$(grep -n 'simctl bootstatus' "$LEASE" | head -1 | cut -d: -f1 || true)"
if [[ -n "$ln_udid" && -n "$ln_guard" && -n "$ln_boot" ]]; then
  (( ln_udid < ln_guard && ln_guard < ln_boot )) \
    && ok "B2 guard sits after the udid ($ln_udid) and before boot ($ln_boot) at line $ln_guard" \
    || fail_t "B2 wrong order: udid=$ln_udid guard=$ln_guard boot=$ln_boot"
else
  fail_t "B2 could not locate all three anchors (udid=$ln_udid guard=$ln_guard boot=$ln_boot)"
fi

# A refusal must free the slot and try the next one. Returning the udid anyway,
# or aborting the whole lease, are both wrong: the first hands over the device,
# the second turns one dirty sim into a total outage of `--ui`.
#
# The window is bounded by the guard's OWN `fi`, not by "the first continue".
# Measured: with the branch body replaced by `return 1`, an unbounded window
# runs on into the boot-failure block below — which contains both `rm -rf` and
# `continue` — and this assertion goes green while blessing a pool-wide outage.
guard_branch="$(awk '/simulator_pool_assert_disposable/{f=1} f{print} f&&/^[[:space:]]*fi[[:space:]]*$/{exit}' "$LEASE")"
gb_lines="$(printf '%s\n' "$guard_branch" | grep -c . || true)"
if (( gb_lines > 12 )); then
  fail_t "B3 the guard's if-branch spans $gb_lines lines — unbounded window, the assertion below would grade the wrong code"
elif [[ "$guard_branch" == *"return"* ]]; then
  fail_t "B3 the refusal branch returns — one dirty simulator would abort the whole lease"
elif [[ "$guard_branch" == *"rm -rf"* && "$guard_branch" == *"continue"* ]]; then
  ok "B3 refusal releases the lease dir and continues to the next slot (branch = $gb_lines lines)"
else
  fail_t "B3 refusal branch does not both release the slot and continue"
fi

# The reader must be wired in too — a guard fed a hardcoded "" is always green.
grep -q 'simulator_pool_read_user_id' "$LEASE" \
  && ok "B4 the guard is fed by simulator_pool_read_user_id, not a literal" \
  || fail_t "B4 cmd_simulator_lease never reads a KGUserId — the guard is fed nothing"

# The caller must keep the two refusal modes apart, or the exhaustion message
# blames logged-in accounts for what is actually a broken detector.
if grep -q 'refused_unverifiable' "$LEASE" && grep -q 'refused_identity' "$LEASE"; then
  ok "B5 the lease counts the two refusal modes separately"
else
  fail_t "B5 cmd_simulator_lease collapses both refusal modes into one counter"
fi

# Catalog erases immediately after leasing, so booting here would add a whole
# redundant cold boot before the erase. The internal seam may skip only this
# boot step; identity validation and lease ownership must still run first.
if grep -q 'SIM_LEASE_SKIP_BOOT' "$LEASE" \
   && awk '/simulator_pool_assert_disposable/{guard=NR} /SIM_LEASE_SKIP_BOOT/{skip=NR} END{exit !(guard && skip && guard < skip)}' "$LEASE"; then
  ok "B6 Catalog may skip only the redundant post-guard lease boot"
else
  fail_t "B6 SIM_LEASE_SKIP_BOOT missing or bypasses the disposability guard"
fi

# ── C. the reader does not need the device booted ────────────────────────────
section "C. reader is boot-independent (macOS)"
if ! command -v plutil >/dev/null 2>&1; then
  skip_t "C1-C4: plutil absent (macOS-only userland); guard logic + wiring above still ran"
else
  READER="$TMP/reader.sh"
  { extract_fn simulator_pool_read_user_id; extract_fn simulator_device_state; } >"$READER"
  # `-s $READER` would be satisfied by simulator_device_state alone. Assert the
  # function under test is really defined, or C2/C4 grade an empty file.
  if bash -c 'set -u; . "$1"; declare -F simulator_pool_read_user_id >/dev/null' _ "$READER" 2>/dev/null; then
    ok "C1 simulator_pool_read_user_id extracted and loads standalone"
  else
    fail_t "C1 simulator_pool_read_user_id missing"
  fi

  # Synthetic device tree, same shape as CoreSimulator's. Two app containers on
  # the dirty device, mirroring the real kg-pool-2 (148 of them on disk).
  mk_device() { # <udid> <container> [KGUserId]
    local dir="$TMP/devices/$1/data/Containers/Data/Application/$2/Library/Preferences"
    mkdir -p "$dir"
    if [[ -n "${3:-}" ]]; then
      cat >"$dir/com.Max0228.BooksBrowser.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>KGUserId</key><string>$3</string></dict></plist>
PLIST
    fi
  }
  mk_device DIRTY-UDID AAAA ""                   # container with no prefs at all
  mk_device DIRTY-UDID BBBB "000287.04e2f0228"   # the real account
  mk_device CLEAN-UDID CCCC ""

  # xcrun masked with an exit-127 stub that also LOGS its argv: whatever the
  # reader finds, it did not find it by talking to a simulator — and the log
  # turns "this code is read-only" from a claim into an assertion.
  SHIM="$TMP/shim"; mkdir -p "$SHIM"
  XCRUN_LOG="$TMP/xcrun.argv"; : >"$XCRUN_LOG"
  printf '#!/bin/sh\necho "$@" >> "%s"\nexit 127\n' "$XCRUN_LOG" >"$SHIM/xcrun"
  chmod +x "$SHIM/xcrun"

  read_it() { # <udid> -> stdout
    PATH="$SHIM:$PATH" KG_IOS_SIM_DEVICES_ROOT="$TMP/devices" \
      bash -c 'set -uo pipefail; . "$1"; simulator_pool_read_user_id "$2"' _ "$READER" "$1" 2>/dev/null
  }

  got="$(read_it DIRTY-UDID || true)"
  [[ "$got" == *"000287.04e2f0228"* ]] \
    && ok "C2 reader found the account with xcrun DENIED and the device never booted" \
    || fail_t "C2 reader returned '${got:-<empty>}' — a spawn-only reader is blind on a Shutdown pool sim"

  got_clean="$(read_it CLEAN-UDID || true)"
  [[ -z "$(printf '%s' "$got_clean" | tr -d '[:space:]')" ]] \
    && ok "C3 control: a clean device reads empty (so C2 is not matching noise)" \
    || fail_t "C3 clean device returned '$got_clean' — the reader invents values"

  # End to end at function level: reader -> guard.
  # Sets E2E_RC. Same 127 discipline as expect_refuse: a missing function must
  # never be able to impersonate a refusal.
  e2e() { # <udid>
    E2E_RC=0
    PATH="$SHIM:$PATH" KG_IOS_SIM_DEVICES_ROOT="$TMP/devices" \
      bash -c 'set -uo pipefail; . "$1"; . "$2"; simulator_pool_assert_disposable "$3" "$(simulator_pool_read_user_id "$3")"' \
      _ "$READER" "$TMP/guard.sh" "$1" >/dev/null 2>&1 || E2E_RC=$?
  }
  extract_fn simulator_pool_assert_disposable >"$TMP/guard.sh"
  e2e CLEAN-UDID
  (( E2E_RC == 0 )) && ok "C4 end-to-end: clean device is leasable" \
                    || fail_t "C4 clean device was refused (rc=$E2E_RC)"
  e2e DIRTY-UDID
  if (( E2E_RC == 0 )); then
    fail_t "C4b DIRTY device was ALLOWED end-to-end"
  elif (( E2E_RC == 127 )); then
    fail_t "C4b rc=127 came from a missing function, not a refusal"
  else
    ok "C4b end-to-end: the device holding a real account is refused (rc=$E2E_RC)"
  fi

  # No mutating simctl verb was ever attempted. `defaults read` on a booted
  # device is the only xcrun call this code may make.
  if grep -qE '(^| )(boot|erase|shutdown|install|uninstall|delete|create) ' "$XCRUN_LOG" 2>/dev/null; then
    fail_t "C5 the reader attempted a mutating simctl verb: $(cat "$XCRUN_LOG")"
  else
    ok "C5 no mutating simctl verb attempted (xcrun argv log asserted, not assumed)"
  fi

  # ── fail-closed: blindness must never read as clean ────────────────────────
  # Each case below removes one thing the reader depends on, against the DIRTY
  # device. The old shape returned empty for all of them, and empty = allow, so
  # a production account was ALLOWED whenever the guard merely lost its sight.
  section "C. fail-closed when the guard cannot see"
  blind_e2e() { # <udid> <extra-PATH-shim-dir> <devices-root>
    BLIND_RC=0
    PATH="$2:$PATH" KG_IOS_SIM_DEVICES_ROOT="$3" \
      bash -c 'set -uo pipefail; . "$1"; . "$2"; simulator_pool_assert_disposable "$3" "$(simulator_pool_read_user_id "$3")"' \
      _ "$READER" "$TMP/guard.sh" "$1" >/dev/null 2>&1 || BLIND_RC=$?
  }
  expect_blind_refusal() { # <label> <udid> <shim> <root>
    blind_e2e "$2" "$3" "$4"
    if (( BLIND_RC == 0 )); then
      fail_t "$1: ALLOWED — an unverifiable device read as disposable"
    elif (( BLIND_RC == 127 )); then
      fail_t "$1: rc=127 came from a missing function, not a refusal"
    else
      ok "$1: refused (rc=$BLIND_RC)"
    fi
  }

  # plutil ABSENT — the reader's only way of parsing a binary plist.
  #
  # PATH is emptied rather than shimmed. A stub *named* plutil satisfies
  # `command -v`, so shimming it silently exercises the malformed-plist branch
  # instead of the missing-plutil branch: measured — with the plutil-missing
  # sentinel deleted from the lib, the shimmed version of this case stayed
  # GREEN. Both branches now get their own case, named for what they run.
  # /bin/bash by absolute path: a `PATH=… bash` prefix applies to the lookup of
  # `bash` ITSELF, so an emptied PATH makes the harness die 127 before the code
  # under test ever runs — and 127 is the very status this file refuses to read
  # as a refusal.
  EMPTYBIN="$TMP/emptybin"; mkdir -p "$EMPTYBIN"
  BLIND_RC=0
  PATH="$EMPTYBIN" KG_IOS_SIM_DEVICES_ROOT="$TMP/devices" \
    /bin/bash -c 'set -uo pipefail; . "$1"; . "$2"; simulator_pool_assert_disposable "$3" "$(simulator_pool_read_user_id "$3")"' \
    _ "$READER" "$TMP/guard.sh" DIRTY-UDID >/dev/null 2>&1 || BLIND_RC=$?
  if (( BLIND_RC == 0 )); then
    fail_t "C6 plutil absent: ALLOWED — losing the parser reads as a clean device"
  elif (( BLIND_RC == 127 )); then
    fail_t "C6 rc=127 came from a missing function, not a refusal"
  else
    ok "C6 plutil absent (PATH emptied): refused (rc=$BLIND_RC)"
  fi

  # plutil PRESENT but broken/incompatible — a different branch from C6.
  BADPLUTIL="$TMP/badplutil"; mkdir -p "$BADPLUTIL"
  printf '#!/bin/sh\nexit 127\n' >"$BADPLUTIL/plutil"; chmod +x "$BADPLUTIL/plutil"
  expect_blind_refusal "C6b plutil present but failing" DIRTY-UDID "$BADPLUTIL:$SHIM" "$TMP/devices"

  # Wrong devices root — i.e. the CoreSimulator layout moved, or the test seam
  # itself is misconfigured. The seam must fail CLOSED, or it is an off-switch.
  expect_blind_refusal "C7 devices root points nowhere" DIRTY-UDID "$SHIM" "$TMP/nonexistent-root"

  # An existing but unreadable prefs plist (permissions), and a corrupt one.
  mk_device PERM-UDID DDDD "000287.04e2f0228"
  chmod 000 "$TMP/devices/PERM-UDID/data/Containers/Data/Application/DDDD/Library/Preferences/com.Max0228.BooksBrowser.plist"
  expect_blind_refusal "C8 prefs plist unreadable" PERM-UDID "$SHIM" "$TMP/devices"

  mk_device CORRUPT-UDID EEEE "placeholder"
  printf 'bplist00\x01\x02truncated-garbage' \
    >"$TMP/devices/CORRUPT-UDID/data/Containers/Data/Application/EEEE/Library/Preferences/com.Max0228.BooksBrowser.plist"
  expect_blind_refusal "C9 prefs plist malformed" CORRUPT-UDID "$SHIM" "$TMP/devices"

  # Control for C6-C9: the clean device must STILL be leasable, or "refuse
  # everything" would pass this whole section while bricking the pool.
  blind_e2e CLEAN-UDID "$SHIM" "$TMP/devices"
  (( BLIND_RC == 0 )) \
    && ok "C10 control: the clean device is still leasable (this is not blanket refusal)" \
    || fail_t "C10 the clean device was refused (rc=$BLIND_RC) — the guard now bricks the pool"
fi

# ── E. the bundle id cannot drift silently ───────────────────────────────────
# The reader hardcodes the app's bundle id on purpose (an env override would be
# a one-variable off-switch for a data-loss guard). The cost of hardcoding is
# drift, so pin the literal against the iOS project's own declaration: rename
# the app there and this goes red instead of the guard going quietly blind.
section "E. bundle id is pinned to the iOS project"
PBXPROJ="$WORKSPACE/ios/BooksAndVocab.xcodeproj/project.pbxproj"
lib_bundle="$(extract_fn simulator_pool_read_user_id | sed -n 's/.*[^_]bundle="\([^"]*\)".*/\1/p' | head -1)"
if [[ -z "$lib_bundle" ]]; then
  fail_t "E1 could not read the hardcoded bundle id out of the reader — the probe is broken"
elif [[ ! -f "$PBXPROJ" ]]; then
  skip_t "E1: $PBXPROJ absent"
elif grep -qF "PRODUCT_BUNDLE_IDENTIFIER = $lib_bundle;" "$PBXPROJ"; then
  ok "E1 reader's bundle id ($lib_bundle) matches PRODUCT_BUNDLE_IDENTIFIER in the pbxproj"
else
  fail_t "E1 reader reads prefs for '$lib_bundle', which no longer exists in the pbxproj — the guard is looking at the wrong app"
fi

# ── D. self-checks ───────────────────────────────────────────────────────────
section "D. self-checks"
[[ -x "$0" ]] && ok "D1 test file has the exec bit" || fail_t "D1 test file is not executable (dispatched as ./ops/tests/…)"

echo ""
echo "passed: $pass  failed: $fail  skipped: $skipped"
[[ $fail -eq 0 ]]
