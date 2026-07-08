# fixture_dataset_env.sh — shared producer for the UI World injection env.
#
# Contract (mirrors ios FixtureDatasetStore):
#   KG_FIXTURE_DATASET_DEFLATE_B64 = base64(raw DEFLATE(UI World JSON bytes))
#
# Why deflate: the plist/env injection chain ends in a posix_spawn env block
# with a ~1MB ceiling. Plaintext base64 of a multi-MB world silently never
# reaches the app process (the world loads as "absent", not as an error).
# Raw DEFLATE (no zlib/gzip container, Python wbits=-15) matches Apple
# `NSData.decompressed(using: .zlib)` on the consumer side.
#
# The legacy plaintext KG_FIXTURE_DATASET_B64 key is still accepted by the app
# for external workflows, but repo tooling must produce the deflate form only —
# setting both keys is a fail-loud error in the app.

kg_fixture_dataset_env_uv_bin() {
  if [[ -n "${UV_BIN:-}" ]]; then
    printf '%s\n' "$UV_BIN"
  elif [[ -x "$HOME/.local/bin/uv" ]]; then
    printf '%s\n' "$HOME/.local/bin/uv"
  else
    printf '%s\n' "uv"
  fi
}

# kg_fixture_dataset_deflate_b64 <dataset_json_path>
# stdout: single-line base64 of the raw-DEFLATE-compressed file bytes.
# empty arg → no-op success (mirrors catalog_dataset_base64 semantics);
# missing file → return 1.
kg_fixture_dataset_deflate_b64() {
  local dataset_path="$1"
  [[ -n "$dataset_path" ]] || return 0
  [[ -f "$dataset_path" ]] || return 1
  "$(kg_fixture_dataset_env_uv_bin)" run --python 3.13 python - "$dataset_path" <<'PY'
import base64
import sys
import zlib

data = open(sys.argv[1], "rb").read()
compressor = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw DEFLATE == Apple .zlib
sys.stdout.write(base64.b64encode(compressor.compress(data) + compressor.flush()).decode("ascii"))
PY
}
