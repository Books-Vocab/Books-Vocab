#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SAFE="$ROOT/ops/devops_kg_safe.sh"

echo "== Safe Status =="
"$SAFE" status

echo ""
echo "== Safe Health =="
"$SAFE" health
