#!/usr/bin/env bash
# kg 懸賞板端到端自檢。在 felix 的 KG clone 內跑：ops/kg_board/selftest.sh
#
# 每一項都問「這件事現在是不是真的」，不問「設定看起來對不對」——一個宣稱自己健康
# 但其實讀著三天前資料的看板，比一個明說壞掉的看板危險。
set -uo pipefail

BASE="${KG_BOARD_BASE:-http://100.118.39.104:8007}"
CLONE="${KG_BOARD_CLONE:-$HOME/kg-board}"
STATE="${KG_BOARD_STATE:-$HOME/kg-board-state}"
TOKEN_FILE="${KG_BOARD_TOKEN_FILE:-$HOME/.secrets/kg-board.token}"
fail=0
ok(){ printf '  ✓ %s\n' "$1"; }
bad(){ printf '  ✗ %s\n' "$1"; fail=$((fail+1)); }
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/kg-board-selftest.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT
health_file="$tmp_dir/health.json"
page_file="$tmp_dir/index.html"
TOKEN=$(cat "$TOKEN_FILE" 2>/dev/null)
READ_AUTH=(-H "Authorization: Bearer $TOKEN")
ORIGIN="${BASE%/}"

echo "kg-board selftest — $BASE"

# 1. 服務活著且自認健康
code=$(curl -fsS "${READ_AUTH[@]}" -o "$health_file" -w '%{http_code}' "$BASE/healthz" 2>/dev/null) \
  && [ "$code" = 200 ] && ok "healthz 200" || bad "healthz 回 ${code:-連不上}（503 = 服務活著但讀不到資料，看下面）"

# 2. 新鮮度：clone 的 HEAD 必須等於 origin/main，且 refresh 沒有錯誤
if [ -d "$CLONE/.git" ]; then
  git -C "$CLONE" fetch -q --prune origin 2>/dev/null
  head=$(git -C "$CLONE" rev-parse HEAD 2>/dev/null)
  origin=$(git -C "$CLONE" rev-parse origin/main 2>/dev/null)
  [ -n "$head" ] && [ "$head" = "$origin" ] \
    && ok "clone 追平 origin/main (${head:0:9})" \
    || bad "clone ${head:0:9} != origin/main ${origin:0:9}（refresh 執行緒沒在跑，或 fetch 失敗）"
else
  bad "沒有 clone：$CLONE"
fi
err=$(uv run --no-project --python 3.13 python -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("read_error") or d["refresh"].get("last_error") or "")' "$health_file" 2>/dev/null)
[ -z "$err" ] && ok "refresh / read 無錯誤" || bad "錯誤：$err"
lag=$(uv run --no-project --python 3.13 python -c '
import json, sys
d = json.load(open(sys.argv[1]))
for key in ("clone_behind_origin", "local_ahead"):
    assert key in d, "%s missing" % key
    assert d[key] is None or isinstance(d[key], int), "%s must be int|null" % key
print("clone_behind_origin=%s local_ahead=%s state=%s" %
      (d["clone_behind_origin"], d["local_ahead"], d.get("freshness_state")))' "$health_file" 2>&1)
[ $? -eq 0 ] && ok "freshness 落後量：$lag" || bad "freshness 落後量：$lag"
revision=$(uv run --no-project --python 3.13 python -c '
import json, sys
d=json.load(open(sys.argv[1]))
value=d.get("app_revision")
assert isinstance(value, str) and value, "app_revision missing"
print(value[:9])' "$health_file" 2>&1)
[ $? -eq 0 ] && ok "應用版本固定：$revision" || bad "應用版本：$revision"

# 2b. HTML 契約：短期 CSRF 只注入同源頁，不把長期 bearer 暴露給瀏覽器
code=$(curl -fsS "${READ_AUTH[@]}" -o "$page_file" -w '%{http_code}' "$BASE/" 2>/dev/null)
CSRF=$(uv run --no-project --python 3.13 python -c '
from html.parser import HTMLParser
import sys
class Meta(HTMLParser):
    value = ""
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "kg-csrf":
            self.value = attrs.get("content", "")
p=Meta(); p.feed(open(sys.argv[1], encoding="utf-8").read())
assert p.value, "kg-csrf meta missing"
print(p.value)' "$page_file" 2>/dev/null)
if [ "$code" = 200 ] && [ -n "$CSRF" ] \
   && grep -q 'data-tab="blocked"' "$page_file" \
   && grep -q '/assets/app.js' "$page_file" \
   && ! grep -q 'Bearer ' "$page_file"; then
  ok "mobile HTML / assets / ephemeral CSRF 契約"
else
  bad "mobile HTML / assets / ephemeral CSRF 契約失敗"
fi

# 3. 資料面：看板真的算得出數字，而且「可派工」只有一個定義
counts=$(curl -fsS "${READ_AUTH[@]}" "$BASE/api/board" 2>/dev/null | uv run --no-project --python 3.13 python -c '
import json, sys
d = json.load(sys.stdin)
c = d["counts"]
assert c["ready_definition"].startswith("KG CLI groomed clause"), c["ready_definition"]
assert c["ready"] == len([r for r in d["board"] if r["ready"]]), "ready 計數與 board 的旗標不一致"
assert c["dispatch"] == len(d["dispatch"]), "dispatch 計數與清單長度不一致"
assert c["decision"]["deferred"] == len(d["deferred"]), "deferred 計數與清單長度不一致"
meta = d["dispatch_meta"]
assert "unblocked" in meta["clauses"], meta["clauses"]
withheld = {row["id"] for row in meta.get("withheld_blocked", [])}
offered = {row["id"] for row in d["dispatch"]}
assert not withheld.intersection(offered), "blocked_by 票流進 dispatch"
print("%s 未解 / %s 總數 / canonical %s / mirror 後 %s / blocked %s" %
      (c["unresolved"], c["total"], c["canonical_dispatch"], c["dispatch"], len(withheld)))' 2>&1)
[ $? -eq 0 ] && ok "board 投影一致：$counts" || bad "board 投影：$counts"

# 3b. 派工清單必須扣掉已被認領的票（憲法三 clause 的第三條，2026-08-08 前缺席）
disp=$(curl -fsS "${READ_AUTH[@]}" "$BASE/api/board" 2>/dev/null | uv run --no-project --python 3.13 python -c '
import json, sys
d = json.load(sys.stdin)
c = d["counts"]
# 認領集合必須是 canonical list 的本機 ledger 與 mirror 的聯集；來源分類留在 row.held.sources。
held_rows = [r for r in d["board"] if r.get("held")]
held = {r["id"] for r in held_rows}
offered = {r["id"] for r in d["dispatch"]}
leak = sorted(offered.intersection(held))
assert not leak, "派工清單含已認領：%s" % leak
bad_sources = sorted(r["id"] for r in held_rows
                     if not set(r["held"].get("sources") or []).intersection({"local", "mirror"}))
assert not bad_sources, "held 缺 local/mirror 來源分類：%s" % bad_sources
assert c["dispatch"] == len(d["dispatch"]), "dispatch 計數與清單長度不一致"
assert c["held"] == len([r for r in d["board"] if r.get("held")]), "held 計數與旗標不一致"
# 沒有任何認領時這條斷言是空的——說出來，別讓沉默看起來像通過
print("VACUOUS" if not held else
      "%d 條認領全部被扣掉，可派工 %d（梳理好 %d）" % (len(held), c["dispatch"], c["ready"]))' 2>&1)
rc=$?
if [ "$rc" -ne 0 ]; then
  bad "派工扣認領：$disp"
elif [ "$disp" = VACUOUS ]; then
  ok "派工扣認領：此刻沒有任何認領，這條檢查證明不了東西（正控缺席，開一條工作樹再跑）"
else
  ok "派工扣認領：$disp"
fi

# 4. 寫入面的三道門，逐一驗它真的擋
[ -s "$TOKEN_FILE" ] && ok "token 檔存在" || bad "token 檔缺失或空：$TOKEN_FILE（服務會拒絕啟動）"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/priority" \
     -H 'Content-Type: application/x-www-form-urlencoded' -H "Origin: $ORIGIN" \
     -H "X-KG-CSRF: $CSRF" -d 'id=X')
[ "$c" = 403 ] && ok "非 JSON content-type 被擋 (403)" || bad "表單型 content-type 拿到 $c，CSRF 門沒關"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/priority" \
     -H 'Content-Type: application/json' -H "Origin: $ORIGIN" \
     -H "Authorization: Bearer $TOKEN" -d '{"id":"X"}')
[ "$c" = 403 ] && ok "priority 缺 CSRF 被擋 (403)" || bad "priority 缺 CSRF 拿到 $c"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/priority" \
     -H 'Content-Type: application/json' -H "X-KG-CSRF: $CSRF" \
     -H 'Origin: http://evil.example' -d '{"id":"X"}')
[ "$c" = 403 ] && ok "跨來源被擋 (403)" || bad "跨來源拿到 $c"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/priority" \
     -H 'Content-Type: application/json' -H "X-KG-CSRF: $CSRF" \
     -H 'Host: evil.example' -H 'Origin: http://evil.example' -d '{"id":"X"}')
[ "$c" = 403 ] && ok "Host/Origin 同時偽造仍被 allowlist 擋 (403)" || bad "DNS rebinding 形狀拿到 $c"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/mirror/claims" \
     -H 'Content-Type: application/json' -H "Origin: $ORIGIN" \
     -H "X-KG-CSRF: $CSRF" -d '{}')
[ "$c" = 401 ] && ok "mirror 拒絕 CSRF、仍要求 bearer (401)" || bad "mirror 無 bearer 拿到 $c"

# 5. 真的寫得進去，而且寫完讀得到——然後清掉這筆自檢資料
probe="SELFTEST-$$"
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/priority" \
     -H 'Content-Type: application/json' -H "Origin: $ORIGIN" -H "X-KG-CSRF: $CSRF" \
     -d "{\"id\":\"$probe\",\"rank\":1}")
if [ "$c" = 200 ]; then
  grep -q "$probe" "$STATE/overlay.json" 2>/dev/null && ok "覆蓋層寫入落地" || bad "回 200 但 overlay.json 沒有那筆"
  # GC 的正控：這個 id 不在 store 裡，所以下一次讀板就該把它掃掉
  curl -fsS "${READ_AUTH[@]}" "$BASE/api/board" >/dev/null 2>&1
  grep -q "$probe" "$STATE/overlay.json" 2>/dev/null \
    && bad "覆蓋層 GC 沒把不存在的 id 掃掉（檔案會無限長大）" \
    || ok "覆蓋層 GC 掃掉了不存在的 id"
else
  bad "帶齊三道門的寫入拿到 $c"
fi

# 6. log 有在轉檔的設定（只驗檔在、可寫；大小門檻由程式自己守）
[ -f "$STATE/kg-board.log" ] && ok "應用 log 在 $STATE/kg-board.log" || bad "沒有應用 log——服務可能從未啟動成功"

echo
[ "$fail" -eq 0 ] && echo "selftest: 全綠" || echo "selftest: $fail 項失敗"
exit "$fail"
