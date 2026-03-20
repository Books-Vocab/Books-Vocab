# Multi-Agent Dashboard 整合指南

為 `/parallel-dev` 流程提供即時可視化觀測。Dashboard 是可選的——未啟動時所有 hooks 靜默失敗，不影響正常開發。

## 架構

```
Claude Code (main + subagents)
  │  hooks (async, 不阻塞)
  ▼
~/.claude/hooks/dashboard-event.sh
  │  HTTP POST
  ▼
Node Server (:3001) + WebSocket (:8766) + SQLite
  │
  ▼
React Dashboard (:5174)
```

每個 Claude Code instance（含 plan-executor subagent）都有獨立 session_id，Dashboard 自動分 swim lane。

## 安裝

### 1. Clone + 修復依賴

```bash
git clone https://github.com/TheAIuniversity/multi-agent-dashboard.git ~/multi-agent-dashboard
cd ~/multi-agent-dashboard/apps/server
npm install
npm install better-sqlite3@latest  # Node 25+ 需要升級此 native module

cd ~/multi-agent-dashboard/apps/client
npm install
```

### 2. 設定 Server 環境

```bash
cp ~/multi-agent-dashboard/apps/server/.env.example ~/multi-agent-dashboard/apps/server/.env
```

`.env` 預設值即可用於本機開發，無需修改。若需 AI 摘要功能（agent 完成時自動生成任務摘要），填入 `ANTHROPIC_API_KEY`。

### 3. 修復 Server 初始化 Bug

原始碼有 SQLite 表建立 race condition，需要兩處修改：

**`apps/server/index.js`** — 將所有 `db.run(CREATE TABLE ...)` 和 `initAuthTables(db)` + `setupAuthRoutes(app, db)` 包進 `db.serialize(() => { ... })`，移除原本在外面的 `initAuthTables`/`setupAuthRoutes` 呼叫。同時，檔案底部的 `agent_registrations` 和 `metrics` 表建立也包進 `db.serialize()`。

**`apps/server/task-queue.js`** — `initDatabase()` 方法內的 `this.db.run(CREATE TABLE ...)` 和索引建立也包進 `this.db.serialize(() => { ... })`。

### 4. 擴展允許的事件類型

**`apps/server/middleware/security.js`** — 在 `validateEvent` 的 `event_type` `.isIn([...])` 陣列中加入：

```
'BatchStart', 'BatchComplete', 'PRMerged', 'BuildStart', 'BuildResult', 'CleanupDone'
```

同時放寬 `session_id` 驗證：
- 正規式改為 `/^[a-zA-Z0-9._-]+$/`
- 長度範圍改為 `{ min: 4, max: 128 }`

### 5. 註冊帳號

```bash
# 先啟動 server
cd ~/multi-agent-dashboard/apps/server && node index.js &
sleep 3

# 註冊（密碼需 8+ 字，含大小寫和數字）
curl -s -X POST http://localhost:3001/auth/signup \
  -H 'Content-Type: application/json' \
  --data-raw '{"email":"admin@kg.local","password":"KgDashboard2026X","name":"KG Admin"}'
```

回應包含 `apiKey`（格式 `mad_...`），**只顯示一次**，記下來。

### 6. 建立 Hook 腳本

建立 `~/.claude/hooks/dashboard-event.sh`：

```bash
#!/bin/bash
# Reads hook input JSON from stdin, posts to dashboard server.
# Silently fails if dashboard is not running.

API_KEY="<你的 API Key>"
SERVER="http://localhost:3001"
EVENT_TYPE="$1"

input=$(cat)
session_id=$(echo "$input" | jq -r '.session_id // .sessionId // "unknown"' 2>/dev/null)
tool_name=$(echo "$input" | jq -r '.tool_name // .toolName // ""' 2>/dev/null)

session_id=$(echo "$session_id" | tr -cd 'a-zA-Z0-9._-' | head -c 128)
[ ${#session_id} -lt 4 ] && session_id="sess-unknown"

case "$EVENT_TYPE" in
  UserPromptSubmit) summary="User prompt submitted" ;;
  PreToolUse)       summary="Tool: $tool_name" ;;
  PostToolUse)      summary="Done: $tool_name" ;;
  Stop)             summary="Agent completed" ;;
  SubagentStop)     summary="Subagent completed"; EVENT_TYPE="Stop" ;;
  *)                summary="Event: $EVENT_TYPE" ;;
esac

curl -s -X POST "$SERVER/events" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" \
  --data-raw "{\"app\":\"claude-code\",\"session_id\":\"$session_id\",\"event_type\":\"$EVENT_TYPE\",\"payload\":{\"tool\":\"$tool_name\"},\"summary\":\"$summary\"}" \
  2>/dev/null || true
```

```bash
chmod +x ~/.claude/hooks/dashboard-event.sh
```

### 7. 設定 Claude Code Hooks

在 `~/.claude/settings.json` 的頂層加入 `hooks`：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/dashboard-event.sh UserPromptSubmit", "async": true }] }
    ],
    "PreToolUse": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/dashboard-event.sh PreToolUse", "async": true }] }
    ],
    "PostToolUse": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/dashboard-event.sh PostToolUse", "async": true }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/dashboard-event.sh Stop", "async": true }] }
    ],
    "SubagentStop": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/dashboard-event.sh SubagentStop", "async": true }] }
    ]
  }
}
```

重點：所有 hook 都設 `"async": true`，不阻塞 Claude Code。

### 8. 建立啟停腳本（可選）

建立 `~/multi-agent-dashboard/dashboard.sh`：

```bash
#!/bin/bash
SERVER_DIR="$(dirname "$0")/apps/server"
CLIENT_DIR="$(dirname "$0")/apps/client"

case "${1:-status}" in
  start)
    cd "$SERVER_DIR" && node index.js > /dev/null 2>&1 &
    cd "$CLIENT_DIR" && npx vite --port 5174 > /dev/null 2>&1 &
    sleep 2
    echo "Server: http://localhost:3001 | Dashboard: http://localhost:5174"
    ;;
  stop)
    lsof -ti:3001 -ti:8766 -ti:5174 2>/dev/null | xargs kill 2>/dev/null
    echo "Stopped."
    ;;
  status)
    curl -s http://localhost:3001/health > /dev/null 2>&1 && echo "Server: RUNNING" || echo "Server: STOPPED"
    curl -s -o /dev/null http://localhost:5174 2>/dev/null && echo "Dashboard: RUNNING" || echo "Dashboard: STOPPED"
    ;;
esac
```

```bash
chmod +x ~/multi-agent-dashboard/dashboard.sh
```

## 在 parallel-dev 中整合

SKILL.md **不需要修改**——全域 hooks 會自動回報所有 agent 的 tool call。

若要在 Phase 2/3/4/5 推送額外的生命週期事件，在 SKILL.md 對應位置加 curl：

```bash
# Phase 2 開始前 — 批次宣告
BATCH_ID="batch-$(date +%s)"
curl -s -X POST http://localhost:3001/events \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <KEY>' \
  --data-raw '{"app":"parallel-dev","session_id":"'$BATCH_ID'","event_type":"BatchStart","payload":{"plans":["a","b"]},"summary":"Batch: 2 plans"}' \
  2>/dev/null || true

# Phase 3 每次 merge 後
curl ... "event_type":"PRMerged" ... "summary":"PR #42 merged"

# Phase 4 build 結果
curl ... "event_type":"BuildResult" ... "payload":{"success":true}

# Phase 5 完成
curl ... "event_type":"BatchComplete" ... "summary":"2 PRs, 8 files"
```

所有 curl 都加 `2>/dev/null || true`，Dashboard 沒跑不影響流程。

## 移除

```bash
# 1. 從 ~/.claude/settings.json 移除 "hooks" 區塊
# 2. 刪除 hook 腳本
rm -f ~/.claude/hooks/dashboard-event.sh
# 3. 停止並刪除 dashboard
~/multi-agent-dashboard/dashboard.sh stop
rm -rf ~/multi-agent-dashboard
```

## 已知問題

| 問題 | 原因 | 解法 |
|------|------|------|
| Server 啟動 crash `no such table` | SQLite async race condition | 步驟 3 的 `db.serialize()` 修復 |
| `better-sqlite3` 編譯失敗 | Node 25+ 缺 prebuild | `npm install better-sqlite3@latest` |
| 事件被拒 `Invalid event type` | 預設只允許 Claude Code 原生事件 | 步驟 4 擴展白名單 |
| 事件被拒 `Invalid session ID` | 驗證過嚴，不允許 `_` `.` | 步驟 4 放寬正規式 |

## 替代方案

若此方案太重，以下更輕量的選項：

| 方案 | 特點 |
|------|------|
| [KanVibe](https://github.com/rookedsysc/kanvibe) | Kanban + worktree 管理 + 瀏覽器終端，與 Claude Code worktree 有衝突 |
| [claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability) | Bun + Vue，更底層的 tool call trace |
| [Parade](https://github.com/JeremyKalmus/parade) | Claude Code 專用 workflow + 視覺化，綁定自己的 skill 體系 |
| [OpenKanban](https://github.com/TechDufus/openkanban) | Go TUI kanban，每張卡片帶 worktree + terminal |
