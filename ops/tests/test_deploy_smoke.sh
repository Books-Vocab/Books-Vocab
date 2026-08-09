#!/usr/bin/env bash
# test_deploy_smoke.sh — verify_post_deploy() unit tests with mocked curl
#
# 透過 CURL_BIN env 注入 mock curl，覆蓋以下情境：
#   1. all-pass
#   2. system/info HTTP != 200
#   3. system/info version mismatch
#   4. system/info 缺 version 欄位
#   5. /api/health 401（受 auth 保護 → pass）
#   6. /api/health 200（pass）
#   7. /api/health 404（skip，不算失敗）
#   8. /api/health 000（網路斷 → fail）
#   9. /api/health 500（fail）
#  10. SENTRY_VERIFY=1 + sentry-test 401 → pass
#  11. SENTRY_VERIFY=1 + sentry-test 500 → pass（觸發例外）
#  12. SENTRY_VERIFY=1 + sentry-test 404 → fallback 檢查 info body 含 sentry
#  13. KG_SKIP_SMOKE=1 → 直接 return 0

set -uo pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
DEVOPS="$WORKTREE/devops.sh"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

# 生成 mock curl 腳本：透過 fixture 檔指定每個 URL 的 (http_code, body)
# fixture 格式（每行）：URL_SUBSTRING|HTTP_CODE|BODY_LITERAL
make_mock_curl() {
  local fixture="$1"
  local script="$TMPDIR/mock_curl_$RANDOM.sh"
  cat >"$script" <<MOCK
#!/usr/bin/env bash
# mock curl: 解析 -w 格式 + URL，從 fixture 查表
url=""
want_body_plus_http=0
want_http_only=0
for a in "\$@"; do
  case "\$a" in
    -w) next=w ;;
    *)
      if [[ "\${next:-}" == "w" ]]; then
        if [[ "\$a" == *"%{http_code}" ]] && [[ "\$a" == *"\\n"* || "\$a" == *\$'\n'* ]]; then
          want_body_plus_http=1
        elif [[ "\$a" == "%{http_code}" ]]; then
          want_http_only=1
        fi
        next=""
      elif [[ "\$a" == http*://* ]]; then
        url="\$a"
      fi
      ;;
  esac
done
# 查 fixture
fixture="$fixture"
match_line=""
while IFS= read -r line; do
  [[ -z "\$line" || "\$line" == \#* ]] && continue
  sub="\${line%%|*}"
  if [[ "\$url" == *"\$sub"* ]]; then
    match_line="\$line"
    break
  fi
done < "\$fixture"
if [[ -z "\$match_line" ]]; then
  echo "mock_curl: no fixture match for url=\$url" >&2
  exit 7
fi
rest="\${match_line#*|}"
code="\${rest%%|*}"
body="\${rest#*|}"
# 若 code=000，模擬真 curl：先印 HTTP code，再以 non-zero exit 表示網路錯誤
if [[ "\$code" == "000" ]]; then
  if [[ "\$want_body_plus_http" == "1" || "\$want_http_only" == "1" ]]; then
    printf '%s' "\$code"
  fi
  exit 6
fi
if [[ "\$want_body_plus_http" == "1" ]]; then
  printf '%s\n%s' "\$body" "\$code"
elif [[ "\$want_http_only" == "1" ]]; then
  printf '%s' "\$code"
else
  printf '%s' "\$body"
fi
exit 0
MOCK
  chmod +x "$script"
  echo "$script"
}

# devops.sh top-level 會做 `cd $(dirname $0)/backend` 計算 LOCAL_DIR，
# 在 source-from-test 情境下會找不到。我們抽出 verify_post_deploy + helper
# 到隔離 sandbox 檔，避免污染。
SANDBOX="$TMPDIR/devops_sandbox.sh"
{
  echo "#!/usr/bin/env bash"
  echo "set -u"
  echo "info()    { echo \"▶ \$*\"; }"
  echo "ok()      { echo \"✓ \$*\"; }"
  echo "err()     { echo \"✗ \$*\" >&2; exit 1; }"
  echo "section() { echo \"\"; echo \"── \$* ──\"; }"
  echo "run_remote() { return 0; }"
  echo "REMOTE_DIR=\"~/fake\""
  # 抽 verify_post_deploy 整個 function
  awk '/^verify_post_deploy\(\) \{/,/^}$/' "$DEVOPS"
} > "$SANDBOX"

run_case() {
  local name="$1"; shift
  local expect_rc="$1"; shift
  local fixture_content="$1"; shift
  local sha="${1:-abc123}"; shift || true
  local extra_env=("$@")

  local fixture="$TMPDIR/fixture_$RANDOM.txt"
  printf '%s\n' "$fixture_content" > "$fixture"
  local mock; mock="$(make_mock_curl "$fixture")"

  # 在 subshell 跑，避免 env 污染後續 case
  local actual_rc=0
  local out
  out=$(
    set +e
    (
      set +u
      # shellcheck disable=SC1090
      source "$SANDBOX"
      export CURL_BIN="$mock"
      for kv in "${extra_env[@]:-}"; do
        [[ -n "$kv" ]] && export "$kv"
      done
      verify_post_deploy "$sha"
    )
    echo "RC=$?"
  )
  actual_rc=$(printf '%s\n' "$out" | grep -oE 'RC=[0-9]+$' | tail -1 | cut -d= -f2)
  if [[ "$actual_rc" == "$expect_rc" ]]; then
    ok "$name (rc=$actual_rc)"
  else
    fail_t "$name expect rc=$expect_rc got rc=$actual_rc"
    echo "$out" | sed 's/^/      /'
  fi
}

# ── Syntax 先過 ────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$DEVOPS" && ok "devops.sh syntax" || fail_t "devops.sh syntax"

# ── verify_post_deploy 行為 ───────────────────────────────────────────────
section "verify_post_deploy()"

# 1. all pass：info=200 version對齊，health=401（受auth保護）
run_case "all-pass (info=200 ver-match, health=401)" 0 "$(cat <<EOF
/api/system/info|200|{"version":"abc123","uptime_seconds":10}
/api/health|401|{"detail":"Not authenticated"}
EOF
)"

# 2. info HTTP 500
run_case "info HTTP 500 → fail" 1 "$(cat <<EOF
/api/system/info|500|internal error
/api/health|401|x
EOF
)"

# 3. info version mismatch
run_case "info version mismatch → fail" 1 "$(cat <<EOF
/api/system/info|200|{"version":"deadbeef","uptime_seconds":1}
/api/health|401|x
EOF
)"

# 4. info 缺 version 欄位
run_case "info missing version field → fail" 1 "$(cat <<EOF
/api/system/info|200|{"uptime_seconds":1}
/api/health|401|x
EOF
)"

# 5. health 200 也算 pass
run_case "health=200 pass" 0 "$(cat <<EOF
/api/system/info|200|{"version":"abc123"}
/api/health|200|{"ok":true}
EOF
)"

# 6. health 404 → skip
run_case "health=404 skip" 0 "$(cat <<EOF
/api/system/info|200|{"version":"abc123"}
/api/health|404|not found
EOF
)"

# 7. health 000 → fail
run_case "health=000 (network down) → fail" 1 "$(cat <<EOF
/api/system/info|200|{"version":"abc123"}
/api/health|000|
EOF
)"

# 8. health 500 → fail
run_case "health=500 → fail" 1 "$(cat <<EOF
/api/system/info|200|{"version":"abc123"}
/api/health|500|err
EOF
)"

# 9. SENTRY_VERIFY=1 + sentry-test 401 → pass
run_case "sentry verify, sentry-test=401 → pass" 0 "$(cat <<EOF
/api/system/info|200|{"version":"abc123"}
/api/health|401|x
/api/system/sentry-test|401|x
EOF
)" "abc123" "SENTRY_VERIFY=1"

# 10. SENTRY_VERIFY=1 + sentry-test 500 → pass（觸發例外算成功）
run_case "sentry verify, sentry-test=500 → pass" 0 "$(cat <<EOF
/api/system/info|200|{"version":"abc123"}
/api/health|401|x
/api/system/sentry-test|500|deliberate
EOF
)" "abc123" "SENTRY_VERIFY=1"

# 11. SENTRY_VERIFY=1 + sentry-test 404 + info body 無 sentry → 不算失敗
run_case "sentry verify, sentry-test=404 fallback → pass" 0 "$(cat <<EOF
/api/system/info|200|{"version":"abc123","uptime_seconds":1}
/api/health|401|x
/api/system/sentry-test|404|x
EOF
)" "abc123" "SENTRY_VERIFY=1"

# 12. KG_SKIP_SMOKE=1 → 不論 fixture 為何都直接 pass
#     用會失敗的 fixture 確保是 skip 而非實際打
run_case "KG_SKIP_SMOKE=1 short-circuit" 0 "$(cat <<EOF
/api/system/info|500|nope
/api/health|500|nope
EOF
)" "abc123" "KG_SKIP_SMOKE=1"

# ── 結果 ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
