#!/usr/bin/env bash
# .padding(...) lowering contract for swift-ast-dumper (#2455; macOS/local, not wired into Linux CI).
set -u
cd "$(dirname "$0")"
if ! command -v swift >/dev/null 2>&1; then
    echo "SKIP: swift toolchain not found"
    exit 0
fi
swift build >/dev/null 2>&1 || { echo "FAIL: swift build"; exit 1; }
BIN="$(swift build --show-bin-path)/swift-ast-dumper"
OUT="$(mktemp)"; trap 'rm -f "$OUT"' EXIT
"$BIN" fixtures/padding_modifiers.swift >"$OUT" 2>/dev/null || { echo "FAIL: dumper exit"; exit 1; }
fail=0
# assert <struct> <expected "edge|edges|value|nUnparsed">
assert() {
    local got
    got="$(uv run --no-project python -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
r = next(s for s in d["structs"] if s["name"] == sys.argv[2])["root"]
p = [m for m in r["modifiers"] if m["name"] == "padding"]
m = p[0] if p else {}
v = m.get("value", {})
print("|".join([str(m.get("edge", "-")), ",".join(m.get("edges", [])) or "-", str(v.get("value", v.get("kind", "-"))), str(len(r["unparsed"]))]))
' "$OUT" "$1")"
    if [ "$got" = "$2" ]; then echo "PASS: $1"; else echo "FAIL: $1 (got '$got' want '$2')"; fail=1; fi
}
assert PadLoneEdge "horizontal|-|16|0"
assert PadEdgeSet "set|horizontal,vertical|8|0"
assert PadEdgeSetDefault "set|top,bottom|16|0"
assert PadUnknownShape "-|-|-|1"
assert PadNamedEdge "leading|-|4|0"
assert PadAll "all|-|12|0"
assert PadDefault "all|-|16|0"
exit $fail
