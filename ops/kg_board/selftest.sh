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

# 2b. HTML 契約：瀏覽器只讀，不注入任何寫入 token
code=$(curl -fsS "${READ_AUTH[@]}" -o "$page_file" -w '%{http_code}' "$BASE/" 2>/dev/null)
if [ "$code" = 200 ] \
   && grep -q 'data-tab="blocked"' "$page_file" \
   && grep -q '/assets/app.js' "$page_file" \
   && ! grep -q 'kg-csrf' "$page_file" \
   && ! grep -q 'Bearer ' "$page_file"; then
  ok "readonly HTML / assets / no browser token 契約"
else
  bad "readonly HTML / assets / no browser token 契約失敗"
fi

# 3. 資料面：看板真的算得出數字，而且「可派工」只有一個定義
counts=$(curl -fsS "${READ_AUTH[@]}" "$BASE/api/board" 2>/dev/null | uv run --no-project --python 3.13 python -c '
import json, sys
d = json.load(sys.stdin)
assert d["schema"] == "kg.board.v3", d.get("schema")
assert not {"dispatch", "blocked", "deferred", "rank", "pinned", "snoozed"}.intersection(d), "readonly payload 仍有重複或排序欄位"
required = {"id", "brief", "detail", "severity", "stream", "held", "ready",
            "scope", "plan", "fix_site", "acceptance",
            }
assert all(set(row) == required for row in d["board"]), "board row 不是 compact v3"
c = d["counts"]
assert c["ready_definition"].startswith("KG CLI groomed clause"), c["ready_definition"]
assert c["ready"] == len([r for r in d["board"] if r["ready"]]), "ready 計數與 board 的旗標不一致"
assert c["dispatch"] == len(d["dispatch_ids"]), "dispatch 計數與 ID 清單長度不一致"
assert c["decision"]["blocked"] == len(d["blocked_ids"]), "blocked 計數與 ID 清單長度不一致"
assert sum(d["segments"].values()) == c["unresolved"], "segments 不是 unresolved partition"
board_ids = {row["id"] for row in d["board"]}
assert set(d["dispatch_ids"]) <= board_ids
assert set(d["blocked_ids"]) <= board_ids
assert set(d["dispatch_ids"]).isdisjoint(d["blocked_ids"])
meta = d["dispatch_meta"]
assert "unblocked" in meta["clauses"], meta["clauses"]
withheld = {row["id"] for row in meta.get("withheld_blocked", [])}
assert set(d["blocked_ids"]) == withheld.intersection(board_ids), "blocked IDs 與 canonical metadata 不一致"
offered = set(d["dispatch_ids"])
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
offered = set(d["dispatch_ids"])
leak = sorted(offered.intersection(held))
assert not leak, "派工清單含已認領：%s" % leak
bad_sources = sorted(r["id"] for r in held_rows
                     if not set(r["held"].get("sources") or []).intersection({"local", "mirror"}))
assert not bad_sources, "held 缺 local/mirror 來源分類：%s" % bad_sources
assert c["dispatch"] == len(d["dispatch_ids"]), "dispatch 計數與 ID 清單長度不一致"
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

# 4. 使用者寫入面必須不存在；mirror 仍是 bearer-only 內部同步
[ -s "$TOKEN_FILE" ] && ok "token 檔存在" || bad "token 檔缺失或空：${TOKEN_FILE}（服務會拒絕啟動）"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/priority" \
     -H 'Content-Type: application/json' -d '{"id":"X"}')
[ "$c" = 404 ] && ok "priority write endpoint 已移除 (404)" || bad "priority endpoint 拿到 $c"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/mirror/claims" \
     -H 'Content-Type: application/json' -d '{}')
[ "$c" = 401 ] && ok "mirror 無 bearer 被擋 (401)" || bad "mirror 無 bearer 拿到 $c"

# 5. 歷史切換必須是獨立唯讀資料面，且只含已結案票
history=$(curl -fsS "${READ_AUTH[@]}" "$BASE/api/history" 2>/dev/null | uv run --no-project --python 3.13 python -c '
import json, sys
d = json.load(sys.stdin)
assert d["schema"] == "kg.board.history.v1", d.get("schema")
assert d["count"] == len(d["board"])
assert all(row.get("status") in {"fixed", "wont-fix"} for row in d["board"])
print("%d 條歷史票" % d["count"])
' 2>&1)
[ $? -eq 0 ] && ok "history 只讀投影：$history" || bad "history 投影：$history"

# 6. log 有在轉檔的設定（只驗檔在、可寫；大小門檻由程式自己守）
[ -f "$STATE/kg-board.log" ] && ok "應用 log 在 $STATE/kg-board.log" || bad "沒有應用 log——服務可能從未啟動成功"

echo
[ "$fail" -eq 0 ] && echo "selftest: 全綠" || echo "selftest: $fail 項失敗"
exit "$fail"
