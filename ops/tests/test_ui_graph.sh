#!/usr/bin/env bash
# CLI-contract regression for ops/ui_graph.py — exercises the --records-json seam
# only (no Xcode build needed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLI="$OPS_DIR/ui_graph.py"
FIXTURE="$OPS_DIR/fixtures/ui_deadcode/records_graph.json"

pass=0; fail=0
check() { if [[ "$2" -eq 0 ]]; then echo "ok   - $1"; pass=$((pass+1)); else echo "FAIL - $1"; fail=$((fail+1)); fi; }

set +e; uv run "$CLI" --help >/dev/null 2>&1; rc=$?; set -e
check "--help exits 0" "$rc"

out="$(uv run "$CLI" --records-json "$FIXTURE" --json 2>/dev/null)"
printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['schema']=='kg.ui.graph.v1'; assert d['nodeCount']==4; assert d['edgeCount']==2" 2>/dev/null
check "--json schema kg.ui.graph.v1 + 4 nodes / 2 edges" "$?"

printf '%s' "$out" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null
check "--json stdout parses as a single JSON document" "$?"

uv run "$CLI" --records-json "$FIXTURE" --dot 2>/dev/null | grep -q '"Screen" -> "Card";'
check "--dot emits expected edge" "$?"

uv run "$CLI" --records-json "$FIXTURE" --type Card 2>/dev/null | grep -q 'used by (1): Screen'
check "--type focus shows reverse users (impact set)" "$?"

set +e; uv run "$CLI" --records-json /no/such/file.json >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -ne 0 ]]; check "missing --records-json file fails loud (nonzero)" "$?"

echo "---"; echo "passed=$pass failed=$fail"
[[ "$fail" -eq 0 ]]
