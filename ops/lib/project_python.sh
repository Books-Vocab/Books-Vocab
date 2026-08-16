#!/usr/bin/env bash
# Resolve the uv-managed Python interpreter without invoking uv's project
# resolver for stdlib-only ops adapters.

kg_project_uv_bin() {
  local candidate
  if [[ -n "${UV_BIN:-}" ]]; then
    candidate="$UV_BIN"
    if [[ "$candidate" == */* ]]; then
      [[ -x "$candidate" ]] || return 1
      printf '%s\n' "$candidate"
    else
      command -v "$candidate"
    fi
    return
  fi
  if [[ -n "${HOME:-}" && -x "$HOME/.local/bin/uv" ]]; then
    printf '%s\n' "$HOME/.local/bin/uv"
    return 0
  fi
  command -v uv
}

kg_project_python_bin() {
  local project_root="$1" uv_bin uv_cache python_bin
  if [[ -x "$project_root/backend/.venv/bin/python" ]]; then
    printf '%s\n' "$project_root/backend/.venv/bin/python"
    return 0
  fi

  if [[ -n "${UV_BIN:-}" ]]; then
    uv_bin="$UV_BIN"
  elif [[ -x "$HOME/.local/bin/uv" ]]; then
    uv_bin="$HOME/.local/bin/uv"
  else
    uv_bin="uv"
  fi
  uv_cache="$(mktemp -d "${TMPDIR:-/tmp}/kg-python-find-XXXXXX")"
  python_bin="$(UV_CACHE_DIR="$uv_cache" "$uv_bin" python find 3.13 2>/dev/null || true)"
  rm -rf "$uv_cache"
  [[ -x "$python_bin" ]] || return 1
  printf '%s\n' "$python_bin"
}
