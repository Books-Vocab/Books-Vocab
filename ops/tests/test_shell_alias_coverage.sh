#!/usr/bin/env bash
# test_shell_alias_coverage.sh — 證明「某支 ops shell 腳本真的被它的 target 測試執行過」。
#
# Usage:
#   ./ops/tests/test_shell_alias_coverage.sh                  # 等同 --self-test
#   ./ops/tests/test_shell_alias_coverage.sh --self-test      # 正負控自測，不碰 git
#   ./ops/tests/test_shell_alias_coverage.sh --prove <script> # 隔離工作樹實證一對
#   ./ops/tests/test_shell_alias_coverage.sh --help
#
# 為什麼存在（IMP-0055）：worktree_orchestrate.py 的 ops-shell 路由把「target 檔案存在
# 且提到這支腳本」當成覆蓋。那是必要非充分條件，已經漏過真案例。這支器械把腳本在隔離
# 工作樹裡改成惰性（保留全部原文、只讓它不再執行），要求 target 轉紅；不紅就是沒覆蓋。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SELF="$ROOT/ops/tests/test_shell_alias_coverage.sh"
WT_PREFIX="kg-alias-cov"

UV_BIN="${UV_BIN:-}"
if [ -z "$UV_BIN" ]; then
  if [ -x "$HOME/.local/bin/uv" ]; then UV_BIN="$HOME/.local/bin/uv"; else UV_BIN="uv"; fi
fi

cleanup() {
  if [ -n "${WT:-}" ]; then
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    rm -rf "$WT"
  fi
  if [ -n "${SBROOT:-}" ]; then rm -rf "$SBROOT"; fi
  return 0
}
trap cleanup EXIT

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$SELF"; }

# 突變保留腳本全部原文（避免 target 只掃原文而產生假性轉紅），只讓它不再執行。
mutate_in_place() {  # $1 = 要改成惰性的腳本路徑
  local f="$1" tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/kg-alias-mut.XXXXXX")" || return 1
  {
    printf '#!/usr/bin/env bash\n'
    printf 'exit 0\n'
    printf ": <<'KG_IMP0055_INERT_BODY'\n"
    cat "$f"
    printf '\nKG_IMP0055_INERT_BODY\n'
  } >"$tmp" || return 1
  cat "$tmp" >"$f" || return 1
  rm -f "$tmp"
}

run_target() {  # $1=工作目錄 $2=target 相對路徑；回傳 target 的 rc
  ( cd "$1" && bash "$2" ) >/dev/null 2>&1
}

prove_in_dir() {  # $1=工作目錄 $2=腳本相對路徑 $3=target 相對路徑
  local dir="$1" script="$2" target="$3" rc
  run_target "$dir" "$target"; rc=$?
  if [ "$rc" -ne 0 ]; then
    printf 'verdict=BASELINE-RED %s -> %s\n' "$script" "$target"
    return 3
  fi
  if ! mutate_in_place "$dir/$script"; then
    printf 'verdict=MUTATE-FAILED %s -> %s\n' "$script" "$target"
    return 4
  fi
  run_target "$dir" "$target"; rc=$?
  if [ "$rc" -ne 0 ]; then
    printf 'verdict=PROVEN %s -> %s\n' "$script" "$target"
    return 0
  fi
  printf 'verdict=NOT-COVERED %s -> %s\n' "$script" "$target"
  return 1
}

resolve_target() {  # $1=腳本相對路徑；印出 target 相對路徑（空 = 無法路由）
  "$UV_BIN" run --quiet --no-project --python 3.13 python - "$ROOT" "$1" 2>/dev/null <<'PY'
import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
rel = sys.argv[2]
sys.path.insert(0, str(root / "ops"))
spec = importlib.util.spec_from_file_location(
    "worktree_orchestrate", root / "ops" / "worktree_orchestrate.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
print(next((c for c in mod._ops_shell_test_candidates(rel) if (root / c).is_file()), ""))
PY
}

do_prove() {  # $1 = 腳本相對路徑（例：devops.sh）
  local script="$1" target
  if [ ! -f "$ROOT/$script" ]; then
    printf 'verdict=NO-SUCH-SCRIPT %s\n' "$script"
    return 6
  fi
  target="$(resolve_target "$script" | tail -1)"
  if [ -z "$target" ]; then
    printf 'verdict=UNROUTABLE %s\n' "$script"
    return 2
  fi
  WT="$(mktemp -d "${TMPDIR:-/tmp}/${WT_PREFIX}.XXXXXX")" || return 5
  rmdir "$WT" || return 5
  if ! git -C "$ROOT" worktree add --detach "$WT" HEAD >/dev/null 2>&1; then
    printf 'verdict=WORKTREE-FAILED %s -> %s\n' "$script" "$target"
    return 5
  fi
  prove_in_dir "$WT" "$script" "$target"
}

pass=0
fail=0
chk() {  # $1=rc $2=label
  if [ "$1" -eq 0 ]; then printf '  ✓ %s\n' "$2"; pass=$((pass+1))
  else printf '  ✗ %s\n' "$2"; fail=$((fail+1)); fi
}
eq() {  # $1=label $2=got $3=want
  if [ "$2" = "$3" ]; then printf '  ✓ %s\n' "$1"; pass=$((pass+1))
  else printf '  ✗ %s\n     got:  [%s]\n     want: [%s]\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}

make_case() {  # $1=case 名 $2=target 檔內容
  local d="$SBROOT/$1"
  mkdir -p "$d"
  cat >"$d/s.sh" <<'EOS'
#!/usr/bin/env bash
KG_MARKER_STRUCTURE=1
echo KG_MARKER_RUNTIME
EOS
  printf '%s\n' "$2" >"$d/t.sh"
  chmod +x "$d/s.sh" "$d/t.sh"
}

self_test() {
  SBROOT="$(mktemp -d "${TMPDIR:-/tmp}/kg-alias-selftest.XXXXXX")" || return 1
  local out rc

  echo "── 突變形狀的正負控（合成 sandbox，不碰 git）──"

  make_case scanner '#!/usr/bin/env bash
grep -q "KG_MARKER_STRUCTURE=1" s.sh'
  out="$(prove_in_dir "$SBROOT/scanner" s.sh t.sh)"
  eq "A1 只掃描原文的 target 判為 NOT-COVERED" "$out" "verdict=NOT-COVERED s.sh -> t.sh"

  make_case exec '#!/usr/bin/env bash
[ "$(bash s.sh)" = "KG_MARKER_RUNTIME" ]'
  out="$(prove_in_dir "$SBROOT/exec" s.sh t.sh)"
  eq "A2 真的執行腳本的 target 判為 PROVEN" "$out" "verdict=PROVEN s.sh -> t.sh"

  make_case both '#!/usr/bin/env bash
grep -q "KG_MARKER_STRUCTURE=1" s.sh && [ "$(bash s.sh)" = "KG_MARKER_RUNTIME" ]'
  out="$(prove_in_dir "$SBROOT/both" s.sh t.sh)"
  eq "A3 又掃描又執行的 target 判為 PROVEN" "$out" "verdict=PROVEN s.sh -> t.sh"

  make_case baseline '#!/usr/bin/env bash
grep -q "KG_MARKER_NEVER_PRESENT" s.sh'
  out="$(prove_in_dir "$SBROOT/baseline" s.sh t.sh)"
  eq "A4 baseline 就紅的 target 判為 BASELINE-RED" "$out" "verdict=BASELINE-RED s.sh -> t.sh"

  echo ""
  echo "── 突變本身的性質 ──"
  grep -qF 'echo KG_MARKER_RUNTIME' "$SBROOT/scanner/s.sh"
  chk $? "A5 突變保留腳本全部原文"
  out="$(bash "$SBROOT/scanner/s.sh" 2>&1)"; rc=$?
  eq "A6 突變後的腳本執行為 no-op" "$rc:$out" "0:"
  bash -n "$SBROOT/scanner/s.sh" 2>/dev/null
  chk $? "A7 突變後的腳本仍通過 bash -n"

  echo ""
  echo "── target 解析走 worktree_orchestrate.py 本尊 ──"
  out="$(resolve_target devops.sh | tail -1)"
  eq "A8 慣例解析 devops.sh" "$out" "ops/test_devops.sh"
  out="$(resolve_target ops/ios_test.sh | tail -1)"
  eq "A9 alias 解析 ops/ios_test.sh" "$out" "ops/test_ios_test_discovery.sh"
  out="$(resolve_target ops/test_ops.sh | tail -1)"
  eq "A10 UNROUTABLE 名單回空" "$out" ""

  echo ""
  echo "── 交付物與接線 ──"
  [ -x "$ROOT/ops/tests/test_shell_alias_coverage.sh" ]
  chk $? "A11 交付物具 executable bit"
  ( cd "$ROOT" && ./ops/tests/test_shell_alias_coverage.sh --help >/dev/null 2>&1 )
  chk $? "A12 ./ 入口可直接執行"
  awk '/^DEFAULT_TESTS=\(/,/^\)$/' "$ROOT/ops/test_ops.sh" | grep -qx '  alias-coverage'
  chk $? "A13 test_ops.sh DEFAULT_TESTS 註冊 alias-coverage"
  grep -qF './ops/tests/test_shell_alias_coverage.sh --self-test' "$ROOT/ops/test_ops.sh"
  chk $? "A14 test_ops.sh 以 ./ 呼叫本器械並帶 --self-test"
  awk '/^LINUX_GROUPS=\(/,/^\)$/' "$ROOT/ops/tests/test_ops_ci_coverage.sh" | grep -qx '  alias-coverage'
  chk $? "A15 alias-coverage 已歸類為 CI-runnable"
  grep -qF 'alias-coverage' "$ROOT/docs/reference/tech_index.md"
  chk $? "A16 tech_index 收錄 alias-coverage group"

  echo ""
  printf 'self-test: %d passed, %d failed\n' "$pass" "$fail"
  [ "$fail" -eq 0 ]
}

mode="${1:-}"
[ -n "$mode" ] || mode="--self-test"
case "$mode" in
  -h|--help)   usage; exit 0 ;;
  --self-test) self_test; exit $? ;;
  --prove)
    if [ "$#" -ne 2 ]; then
      printf '✗ --prove 需要一個腳本相對路徑（例：--prove devops.sh）\n' >&2
      exit 2
    fi
    do_prove "$2"; exit $?
    ;;
  *)
    printf '✗ unknown argument: %s\n' "$mode" >&2
    usage >&2
    exit 2
    ;;
esac
