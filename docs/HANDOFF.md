# Session 交接文檔 (2026-04-12)

## 本次完成的事項

### 1. Claude Code Gateway 部署
- **本地位置**：`~/kg/lab/claude-code-gateway/`（已在 .gitignore）
- **遠端位置**：`ubuntu@13.193.212.134:~/claude-code-gateway/`
- **公網 endpoint**：`https://wordnexus.lol/claude/v1/chat/completions`
- **API Token**：`.env` 中的 `CCG_API_TOKEN`（Bearer auth）
- **模型別名**：`sonnet` / `opus` / `haiku`（CLI 自動解析最新版）
- **容器名**：`claude-code-gateway-api-1`，port 8090
- **Caddy 路由**：`/claude/*` → strip prefix → localhost:8090
- **CLI 認證**：已在主機上執行 `claude` 互動式登入，Docker 掛載 `~/.claude`

### 2. Lightsail 升級
- **舊 instance**：`booksbrowser-kg-api`（micro_3_0, 1GB, $7/月）— 已刪除
- **新 instance**：`booksbrowser-kg-api-2gb`（small_3_0, 2GB, $12/月）
- **新 IP**：`13.193.212.134`
- **Snapshot 保留**：`kg-upgrade-20260412`
- **本地備份**：`~/kg/backups/data_20260412_1325`

### 3. MPSO → ~/kg 遷移（進行中）
- `mv ~/MPSO/projects/kg ~/kg` 已執行
- **完整備份**：`~/MPSO.backup`
- **本 session 的 Bash sandbox 因路徑變更已壞**，需開新 session 繼續

## 下次 session 需完成的事項

### 遷移收尾（優先）
1. **搬遷 MPSO 獨有文檔到 ~/kg**：
   - `~/MPSO/docs/BACKGROUND.md` → `~/kg/docs/ops/`
   - `~/MPSO/docs/SAFETY_POLICY.md` → `~/kg/docs/ops/`
   - `~/MPSO/docs/SYSTEM_RUNBOOK.md` → `~/kg/docs/ops/`
   - `~/MPSO/scripts/status_all.sh` → `~/kg/ops/`（或合入 devops.sh）
   - `~/MPSO/scripts/verify_agent_ops.sh` → `~/kg/ops/`
   - `~/MPSO/.claude/skills/ops/SKILL.md` — 可廢棄，KG 已有 devops skill

2. **全文路徑替換**：
   ```bash
   # 在 ~/kg 下執行
   find . -type f \( -name "*.md" -o -name "*.sh" -o -name "*.json" \) \
     -not -path './.git/*' -not -path './lab/*' -not -path './.venv/*' \
     -exec grep -l 'MPSO/projects/kg\|MPSO' {} \; | sort -u
   
   # 替換
   # ~/MPSO/projects/kg → ~/kg
   # /Users/chenliangyu/MPSO/projects/kg → /Users/chenliangyu/kg
   ```

3. **Git submodule URL 更新**：
   ```bash
   git config submodule.booksbrowser_ios.url "/Users/chenliangyu/kg/booksbrowser_ios"
   git config submodule.knowledge_graph_api.url "/Users/chenliangyu/kg/knowledge_graph_api"
   ```

4. **Python venv 修復**：
   ```bash
   cd ~/kg/backend && uv pip install -e .
   ```

5. **CLAUDE.md 更新**：
   - 合入 MPSO root CLAUDE.md 中有用的內容（主要是 safety rules）
   - 更新 Identity 表中的 `local root` 為 `.`（不再是 `projects/kg`）
   - 移除所有 `projects/kg` 相對路徑引用

6. **驗證**：
   ```bash
   ./ops/devops_kg_safe.sh preflight
   ./ops/ios_build.sh
   ./ops/ios_test.sh
   git status && git log --oneline -3
   ```

7. **清理**：
   - 確認一切正常後刪除 `~/MPSO` 和 `~/MPSO.backup`

### Gateway 文檔整合（唯一事實文檔）
- 調查所有提及 gateway 的文檔（BACKGROUND.md、deploy.md、debug.md、devops SKILL.md）
- 確定一個唯一事實來源（建議 `docs/dev/deploy.md` 新增 gateway section）
- 其他文檔只引用，不重複內容

### Review 修復殘留
- `~/.claude/skills/ops/SKILL.md` 的 Caddy routing 區塊缺少 Gateway 路由（MPSO 層，搬遷後可廢棄）

## 關鍵資訊速查

| 項目 | 值 |
|------|-----|
| KG 本地路徑 | `~/kg` |
| 遠端 IP | `13.193.212.134` |
| SSH | `ssh -i ~/.ssh/lightsail_default.pem ubuntu@13.193.212.134` |
| Instance | `booksbrowser-kg-api-2gb` |
| KG API | `https://wordnexus.lol` (port 8000) |
| Gateway | `https://wordnexus.lol/claude/v1` (port 8090) |
| Gateway Token | 在 `~/kg/lab/claude-code-gateway/.env` 的 `CCG_API_TOKEN` |
| Git remote | `https://github.com/MaxChen228/Books-Vocab.git` |
| MPSO 備份 | `~/MPSO.backup` |
