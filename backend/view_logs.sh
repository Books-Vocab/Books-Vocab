#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAIL_LINES="${1:-80}"

echo "透過 safe wrapper 查看生產日誌 tail=${TAIL_LINES}..."
exec "$ROOT/ops/devops_kg_safe.sh" logs "$TAIL_LINES"
