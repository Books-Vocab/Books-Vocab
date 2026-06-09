#!/usr/bin/env bash
# CLI-contract regression for ops/ui_deadcode.py — exercises the --records-json
# seam only, so it needs no Xcode build (build orchestration is covered by the
# end-to-end run, not this gate).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLI="$OPS_DIR/ui_deadcode.py"
FIXTURE="$OPS_DIR/fixtures/ui_deadcode/records_sample.json"

pass=0
fail=0
check() { # desc, condition-already-evaluated rc
  if [[ "$2" -eq 0 ]]; then echo "ok   - $1"; pass=$((pass + 1));
  else echo "FAIL - $1"; fail=$((fail + 1)); fi
}

# 1. --help exits 0
set +e
uv run "$CLI" --help >/dev/null 2>&1; rc=$?
set -e
check "--help exits 0" "$rc"

# 2. --records-json --json emits the schema and is valid JSON
out="$(uv run "$CLI" --records-json "$FIXTURE" --json 2>/dev/null)"
printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['schema']=='kg.ui.deadcode.v1'; assert d['orphanCount']==2" 2>/dev/null
check "--json carries schema kg.ui.deadcode.v1 + 2 orphans (struct+class default)" "$?"

# 3. --json stdout is machine-clean (no diagnostics leaking to stdout)
printf '%s' "$out" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null
check "--json stdout parses as a single JSON document" "$?"

# 4. warn-only default exits 0 even with orphans
set +e
uv run "$CLI" --records-json "$FIXTURE" >/dev/null 2>&1; rc=$?
set -e
check "default (warn-only) exits 0 with orphans present" "$rc"

# 5. --strict exits 1 when orphans found
set +e
uv run "$CLI" --records-json "$FIXTURE" --strict >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 1 ]]; check "--strict exits 1 with orphans present" "$?"

# 6. usage error (bad kind) exits 2 via argparse? no — unknown kind is handled in
#    kgindex; here a missing fixture path should fail loudly (nonzero).
set +e
uv run "$CLI" --records-json /no/such/file.json >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -ne 0 ]]; check "missing --records-json file fails loud (nonzero)" "$?"

echo "---"
echo "passed=$pass failed=$fail"
[[ "$fail" -eq 0 ]]
