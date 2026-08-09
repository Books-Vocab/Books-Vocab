#!/usr/bin/env bash
# Executable worktree-gate wrapper for changes to ops/lib/ios_ops_catalog.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEST_FILE="${1:-ops/tests/test_catalog_agent_boundary.py}"
[[ "$TEST_FILE" == "ops/tests/test_catalog_agent_boundary.py" ]] || {
  echo "unexpected Catalog boundary test path: $TEST_FILE" >&2
  exit 2
}

cd "$ROOT"
exec uv run --no-project --python 3.13 --with pytest pytest -q "$TEST_FILE"
