# Ops System Redesign — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 將 dev/ops 關注點分離，解決遠端執行的引號地獄，封裝高頻查詢，加入 admin 密碼登入。
**Architecture:** CLAUDE.md 瘦身 → devops skill 升級 → ops_cli.py 部署進 container → devops.sh 新增子指令 → admin login
**Spec:** `docs/superpowers/specs/2026-04-03-ops-system-redesign.md`

---

### Task 1: ops_cli.py — container 內查詢工具

**Files:**
- Create: `backend/ops_cli.py`
- Create: `backend/tests/test_ops_cli.py`
- Modify: `backend/Dockerfile` (在 `COPY privacy.html ...` 之後、`USER appuser` 之前加 `COPY ops_cli.py ./`)

- [ ] **Step 1: 寫 test**
```python
# backend/tests/test_ops_cli.py
# 測試 ops_cli 的核心函數（定價計算、data dir 解析）
# 用 tmp_path 建立假 token_usage.db 和 cards.db
# 測試：user_quota, user_stats, quota_overview, active_users 的輸出格式
```
Run: `cd backend && python -m pytest tests/test_ops_cli.py -v`
Expected: FAIL (module not found)

- [ ] **Step 2: 實作 ops_cli.py**
純 stdlib，argparse，子指令：user-quota, user-stats, quota-overview, active-users, db-query。
定價常數：INPUT_PER_M=0.10, OUTPUT_PER_M=0.40, EMBED_PER_M=0.00025。
Data dir: `os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent / "data"))`
額度上限: `float(os.getenv("PRO_DAILY_LIMIT_USD", "0.30"))`, `float(os.getenv("FREE_DAILY_LIMIT_USD", "0.03"))`

- [ ] **Step 3: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_ops_cli.py -v`

- [ ] **Step 4: Dockerfile 加 COPY**
```dockerfile
# 在 COPY src/ src/ 附近加
COPY ops_cli.py ./
```

- [ ] **Step 5: 本地驗證 CLI**
Run: `python3 backend/ops_cli.py --help`
Run: `python3 backend/ops_cli.py user-quota 000287.04e254024c2f4341849278a933743257.0228`

- [ ] **Step 6: Commit**
`ops: add ops_cli.py — container-deployed query tool`

---

### Task 2: devops.sh 新增 ops-cli 和 container-script 子指令

**Files:**
- Modify: `devops.sh` (加 cmd_ops_cli, cmd_container_script)
- Modify: `ops/devops_kg_safe.sh` (白名單加 ops-cli, container-script)
- Create: `ops/test_devops_new_cmds.sh` (驗證腳本)

- [ ] **Step 1: devops.sh 加 cmd_ops_cli**
```bash
cmd_ops_cli() {
  [[ -z "${1:-}" ]] && err "用法: $0 ops-cli <subcommand> [args...]"
  cmd_container_run "python3 /app/ops_cli.py $*"
}
```

- [ ] **Step 2: devops.sh 加 cmd_container_script**
```bash
cmd_container_script() {
  local script="${1:-}"
  [[ -z "$script" ]] && err "用法: $0 container-script <local-script.py> [args...]"
  [[ ! -f "$script" ]] && err "檔案不存在: $script"
  local ext="${script##*.}"
  [[ "$ext" == "py" || "$ext" == "sh" ]] || err "只允許 .py 和 .sh: $script"
  local base; base=$(basename "$script")
  local remote_tmp="/tmp/$base"
  info "上傳 $script → container"
  "${SCP_CMD[@]}" "$script" "$SERVER:$remote_tmp"
  run_remote "docker cp $remote_tmp $CONTAINER:$remote_tmp"
  shift
  run_remote "docker exec $CONTAINER python3 $remote_tmp $*"
  run_remote "rm -f $remote_tmp"
}
```

- [ ] **Step 3: devops.sh case 加入新指令**
```bash
ops-cli)      cmd_ops_cli "${@:2}" ;;
container-script) cmd_container_script "${@:2}" ;;
```

- [ ] **Step 4: devops_kg_safe.sh 白名單**
在 main() 的 case 中加入 ops-cli 和 container-script。

- [ ] **Step 5: 驗證**
Run: `./ops/devops_kg_safe.sh ops-cli --help`
Run: 寫一個 `/tmp/test_remote.py`（print hello）然後 `./ops/devops_kg_safe.sh container-script /tmp/test_remote.py`

- [ ] **Step 6: Commit**
`ops: add ops-cli and container-script subcommands`

---

### Task 3: CLAUDE.md 拆分 + devops skill 升級

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/skills/devops/SKILL.md`

- [ ] **Step 1: 從 CLAUDE.md 移除 `## 生產環境操作` 段落**
移除第 50-62 行（從 `## 生產環境操作` 到 data_inspect 用法結束）。

- [ ] **Step 2: 從 `## 對話啟動流程` 移除第 3 點**
將 preflight/backup 時機規則移到 skill 中。

- [ ] **Step 3: 更新 Skill 系統表**
```markdown
| `devops` | 部署 / 狀態 / 用戶查詢 / 額度 / 遠端操作 / 維護 | 生產環境運維全覽 |
```

- [ ] **Step 4: 重寫 devops SKILL.md**
Frontmatter:
```yaml
---
name: devops
description: "KG 生產環境運維 — 部署、狀態、用戶查詢、額度、遠端操作、系統健康"
allowed-tools: Bash, Read, Grep
---
```

內容包含：
1. Identity（server、remote、domain、container、port）
2. 安全規則（preflight/backup 時機）
3. 指令參考（safe wrapper 全指令 + ops-cli + container-script）
4. 高頻操作範例
5. 快速診斷流程
6. 緊急恢復
7. Deep reference

- [ ] **Step 5: 驗證 CLAUDE.md 無 ops 指令參考**
確認 `## 生產環境操作` 段落已不存在。

- [ ] **Step 6: Commit**
`docs: split ops from CLAUDE.md into devops skill`

---

### Task 4: Admin 密碼登入

**Files:**
- Modify: `backend/src/kg/settings.py` (加 admin_password)
- Modify: `backend/src/kg/admin_handlers.py` (加 login 邏輯, get_admin_user_or_redirect)
- Modify: `backend/src/kg/deps.py` (加 get_admin_user_or_redirect)
- Modify: `backend/src/kg/routers/admin.py` (拆 HTML/API 路由, 加 login_router)
- Modify: `backend/src/kg/api.py` (login_router 在 admin_router 之前 include)
- Create: `backend/tests/test_admin_login.py`

- [ ] **Step 1: 寫 test**
```python
# backend/tests/test_admin_login.py
# 測試：
# - GET /admin/login 返回 200 + HTML
# - POST /admin/login 正確密碼 → 302 + Set-Cookie
# - POST /admin/login 錯誤密碼 → 200 + error message
# - POST /admin/login ADMIN_PASSWORD 為空 → 403
# - GET /admin 未認證 → 302 redirect 到 /admin/login
# - GET /api/admin/stats 未認證 → 403 JSON（不是 302）
# - 現有 ADMIN_TOKEN 認證仍正常
```
Run: `cd backend && python -m pytest tests/test_admin_login.py -v`
Expected: FAIL

- [ ] **Step 2: settings.py 加 admin_password**
dataclass 加欄位 + load_settings() 加 os.getenv

- [ ] **Step 3: admin_handlers.py 加 login 邏輯**
- `admin_login_page(error: str = "")` → 返回登入 HTML
- `admin_login_post(password, admin_password, admin_token)` → 驗證 + set cookie + 302
- `ADMIN_LOGIN_HTML` — 極簡登入頁模板

- [ ] **Step 4: deps.py 加 get_admin_user_or_redirect**
仿照 `get_admin_user` 的 `async def` 簽名。認證失敗時返回 `RedirectResponse("/admin/login", 302)` 而非 raise 403。

- [ ] **Step 5: routers/admin.py 拆分路由**
- `login_router = APIRouter()` — 無 dependency，掛 GET/POST `/admin/login`
- HTML 路由（`/admin`, `/admin/tests`）改用 `get_admin_user_or_redirect`
- API 路由（`/api/admin/*`）維持 `get_admin_user`

- [ ] **Step 6: api.py 註冊 login_router**
在 `create_app()` 中，`login_router` 在 `admin_router` 之前 `app.include_router()`。

- [ ] **Step 7: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_admin_login.py -v`

- [ ] **Step 8: 跑全部 admin 相關 test**
Run: `cd backend && python -m pytest tests/test_admin_security.py tests/test_admin_login.py -v`

- [ ] **Step 9: Commit**
`api: add admin password login with /admin/login page`

---

### Task 5: 整合驗證 + Deploy

- [ ] **Step 1: 跑全部 backend test**
Run: `cd backend && python -m pytest -x -v`

- [ ] **Step 2: iOS build 確認無影響**
Run: `./ops/ios_build.sh`

- [ ] **Step 3: 遠端設定 ADMIN_PASSWORD**
提醒使用者在 remote `.env` 加 `ADMIN_PASSWORD=<password>`。

- [ ] **Step 4: Deploy**
Run: `./ops/devops_kg_safe.sh deploy`

- [ ] **Step 5: 驗證 ops-cli**
Run: `./ops/devops_kg_safe.sh ops-cli user-quota 000287.04e254024c2f4341849278a933743257.0228`

- [ ] **Step 6: 驗證 admin login**
瀏覽器開 `https://wordnexus.lol/admin/login`，用密碼登入。

- [ ] **Step 7: 驗證 container-script**
```bash
echo 'print("hello from container")' > /tmp/test_remote.py
./ops/devops_kg_safe.sh container-script /tmp/test_remote.py
```
