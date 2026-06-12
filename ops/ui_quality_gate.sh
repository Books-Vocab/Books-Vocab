#!/usr/bin/env bash
# ui_quality_gate.sh — orchestrate manual UI quality gates.
#
# Thin wrapper around ops/ui_quality_gate.py. See that file for usage.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi

exec "$UV_BIN" run --python 3.13 python ops/ui_quality_gate.py "$@"
