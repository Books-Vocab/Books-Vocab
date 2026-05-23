#!/usr/bin/env bash
# injection_lint.sh — verify InjectionNext three-piece coverage on Views/.
#
# Modes:
#   --report         (default) Print findings, exit 0.
#   --baseline       Write current findings to ops/injection_baseline.txt (with 30-day sunset).
#   --baseline-check Compare to baseline; fail if regressed.
#   --strict         Any finding fails. Use in CI / hooks.
#
# Rules (see ops/injection_lint.py):
#   R1. Each non-private `struct X: View` (excluding Debug/Readium/PDFReader,
#       and structs inside #Preview blocks) must be followed by @ObserveInjection.
#   R2. Per-file: @ObserveInjection count == .enableInjection() count.
#   R3. If file has @ObserveInjection, it must also `import Inject`.

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
exec python3 ops/injection_lint.py "$@"
