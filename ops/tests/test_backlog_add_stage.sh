#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/kg-backlog-add-stage.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

store="$tmp_dir/backlog"
queue="$tmp_dir/backlog_anchor_queue.jsonl"
mkdir -p "$store"

./ops/backlog.py add --help 2>&1 | grep -Fq -- '--stage'
./ops/backlog.py add --help 2>&1 | grep -Fq -- '--queue'

before="$(git status --porcelain)"
output="$(./ops/backlog.py add --stage --queue "$queue" --store "$store" \
  --stream IMP --date 2026-01-01 --source test --category tool --severity low \
  --brief 'probe' --scope 'one staged entry' --detail 'probe' --json)"
after="$(git status --porcelain)"
test "$before" = "$after"

entry_id="$(printf '%s' "$output" | uv run --no-project --python 3.13 python -c \
  'import json,sys; print(json.load(sys.stdin)["entry"]["id"])')"
test -n "$entry_id"
test ! -f "$store/$entry_id.json"
grep -Fq "$entry_id" "$queue"

if ./ops/backlog.py add --stage --queue "$queue" --store "$store" \
  --stream IMP --date 2026-01-01 --source test --category tool --severity low \
  --brief 'probe' --scope 'one staged entry' --detail 'probe' --json; then
  echo "FAIL: duplicate staged id was accepted" >&2
  exit 1
fi

uv run --no-project --python 3.13 python -c '
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
entry_id = sys.argv[2]
rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
assert len(rows) == 1 and rows[0]["id"] == entry_id
rows[0]["landed_sha"] = "a" * 40
path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\\n" for row in rows))
' "$queue" "$entry_id"

anchored="$(./ops/backlog.py anchor --store "$store" --queue "$queue" --commit --json)"
printf '%s' "$anchored" | uv run --no-project --python 3.13 python -c \
  'import json,sys; assert json.load(sys.stdin)["applied"] == [sys.argv[1]]' "$entry_id"
test -f "$store/$entry_id.json"

echo OK
