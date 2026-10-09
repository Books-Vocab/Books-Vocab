#!/usr/bin/env bash
# CLI exit-code contract for swift-ast-dumper (macOS/local; not wired into Linux CI).
set -u
cd "$(dirname "$0")"
if ! command -v swift >/dev/null 2>&1; then
    echo "SKIP: swift toolchain not found"
    exit 0
fi
swift build >/dev/null 2>&1 || { echo "FAIL: swift build"; exit 1; }
BIN="$(swift build --show-bin-path)/swift-ast-dumper"
FIX=fixtures/shape_modifiers.swift
SRC=Sources/swift-ast-dumper/main.swift
ERR="$(mktemp)"; OUT="$(mktemp)"
trap 'rm -f "$ERR" "$OUT"' EXIT
fail=0
check() { if [ "$2" = ok ]; then echo "PASS: $1"; else echo "FAIL: $1"; fail=1; fi; }
run() { "$BIN" "$@" >"$OUT" 2>"$ERR"; return $?; }
nonzero_with_stderr() { # label expected_rc args...
    local label=$1 want=$2; shift 2
    run "$@"; local rc=$?
    if [ "$rc" = "$want" ] && [ -s "$ERR" ]; then check "$label" ok; else check "$label (rc=$rc want=$want)" bad; fi
}

nonzero_with_stderr "no-match --struct exits 1" 1 "$FIX" --struct NoSuchStruct
nonzero_with_stderr "no-match --emit exits 1" 1 "$FIX" --emit NoSuchPathFragment
nonzero_with_stderr "nonexistent file exits 1" 1 "/tmp/swift-ast-dumper-missing-$$.swift"
nonzero_with_stderr "mixed readable+unreadable exits 1" 1 "$FIX" "/tmp/swift-ast-dumper-missing-$$.swift"
nonzero_with_stderr "--struct without value exits 2" 2 "$FIX" --struct
nonzero_with_stderr "--emit without value exits 2" 2 "$FIX" --emit
nonzero_with_stderr "no files exits 2" 2

run "$FIX"; rc=$?
if [ "$rc" = 0 ] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["structs"] and d["skipped"]==[]' "$OUT"; then
    check "happy path exits 0 with JSON" ok
else check "happy path (rc=$rc)" bad; fi

name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["structs"][0]["name"])' "$OUT")"
run "$FIX" --struct "$name"; rc=$?
if [ "$rc" = 0 ]; then check "matching --struct exits 0" ok; else check "matching --struct (rc=$rc)" bad; fi

# numeric literals (#2445): radix / underscores lowered faithfully, overflow -> unknown (never 0)
run fixtures/numeric_literals.swift; rc=$?
got="$(uv run --no-project python -I -c '
import json, sys
r = json.load(open(sys.argv[1]))["structs"][0]["root"]
f = [m["dims"] for m in r["modifiers"] if m["name"] == "frame"]
a, b = f[0], f[1]
out = [a["width"]["value"], a["height"]["value"], a["minWidth"]["value"], a["maxWidth"]["value"], b["idealWidth"]["value"], b["idealHeight"]["kind"], b["idealHeight"]["raw"]]
print(out)
' "$OUT")"
if [ "$rc" = 0 ] && [ "$got" = "[1000, 64, 5, 15, 1000.5, 'unknown', '99999999999999999999']" ]; then check "numeric literals lowered (radix/underscore/overflow)" ok
else check "numeric literals lowered (rc=$rc got=$got)" bad; fi

# ternary foreground (#2449): the first palette.X of a ternary must not be reported as the token
run fixtures/ternary_foreground_color.swift; rc=$?
got="$(uv run --no-project python -I -c '
import json, sys
s = {x["name"]: x["root"] for x in json.load(open(sys.argv[1]))["structs"]}
tok = lambda n: [m["token"] for m in s[n]["modifiers"] if m["name"] == "foreground"][0]
print(tok("TernaryForeground") + "," + tok("PlainForeground"))
' "$OUT")"
if [ "$rc" = 0 ] && [ "$got" = "isSelected,accent" ]; then check "ternary foreground not resolved to first palette token" ok
else check "ternary foreground (rc=$rc got=$got)" bad; fi

# usage string: header comment == stderr usage
hdr="$(grep -m1 '^// Usage: ' "$SRC" | sed 's|^// Usage: ||')"
run; use="$(sed 's/^usage: //' "$ERR" | head -1)"
if [ -n "$hdr" ] && [ "$hdr" = "$use" ]; then check "header usage == stderr usage" ok
else check "header usage == stderr usage ('$hdr' vs '$use')" bad; fi
for tok in '<file.swift>...' '[--struct Name]' '[--emit <filter>]'; do
    case "$use" in *"$tok"*) check "usage names $tok" ok ;; *) check "usage names $tok" bad ;; esac
done
exit $fail
