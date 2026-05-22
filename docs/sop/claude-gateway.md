<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - lab/claude-code-gateway/
verified_against: 8853760
-->
# Claude Code Gateway

KG workspace 的 **Claude subscription → OpenAI-compatible API** 閘道。將本機登入的 Claude Code CLI 包成 `/v1/chat/completions`，供 lab 端 PoC（podcast architect 等）直接用 `openai` SDK 呼叫 Claude 模型，不走 Anthropic API（無 per-token 費用，走訂閱額度）。

> Upstream: `enescingoz/claude-code-gateway`（third-party，透過 subprocess 呼叫 `claude` CLI；未抽取 OAuth token，但仍在 Anthropic 訂閱條款灰區，use at your own risk）。
>
> **Upstream 已於 2026-05 確認從 GitHub 下架**。本目錄為 2025-04-12 snapshot，已 vendored 進 KG monorepo（`git ls-files lab/claude-code-gateway` 38 個檔案），後續維護一律在本地進行，無 upstream 可拉。

## 部署事實

| key | value |
|-----|-------|
| 本地路徑 | `lab/claude-code-gateway/`（vendored 進 monorepo；`.gitignore` 只擋 `.venv/` 與 `.env`） |
| 遠端路徑 | `ubuntu@13.193.212.134:~/claude-code-gateway/` |
| 公網 endpoint | `https://wordnexus.lol/claude/v1` |
| 容器名 | `claude-code-gateway-api-1` |
| 內部 port | `8090` |
| Caddy 路由 | `/claude/*` → strip prefix → `localhost:8090` |
| 認證 | Bearer token（`.env` 的 `CCG_API_TOKEN`） |
| Docker volumes | `~/.claude` + `~/.claude.json`（主機 CLI 登入態） |
| 模型別名 | `sonnet` / `opus` / `haiku`（CLI 自動解析最新版） |

## Caddy 片段（事實來源：`docs/reference/host_topology.md`）

```caddy
wordnexus.lol {
    handle /claude/* {
        uri strip_prefix /claude
        reverse_proxy localhost:8090
    }
    reverse_proxy localhost:8000
}
```

任何修改 Caddyfile 的操作**必須保留** `/claude/*` handle，否則 gateway 斷線。

## 使用方式（OpenAI SDK）

```python
from openai import OpenAI
client = OpenAI(
    base_url="https://wordnexus.lol/claude/v1",
    api_key="<CCG_API_TOKEN>",  # 來自 lab/claude-code-gateway/.env
)
stream = client.chat.completions.create(
    model="opus",  # or "sonnet" / "haiku"
    messages=[{"role": "system", "content": "..."},
              {"role": "user", "content": "..."}],
    stream=True,
)
```

現行呼叫點：`lab/podcast/pipeline.py`（book → production plan）。PoC 已封存於 `lab/archive/podcast_architect_poc.py`。

## 運維注意

- **登入態由主機 CLI 持有**：部署首次需在遠端主機 `claude` 互動登入，容器透過掛載 `~/.claude` 繼承。續訂或帳號換人需重新登入。
- **容器獨立於 KG API**：`knowledge-graph-api`（8000）與 `claude-code-gateway-api-1`（8090）互不依賴，smart deploy 只動 KG API。Gateway 更新需單獨 `docker compose up --build -d` 於遠端 `~/claude-code-gateway/`。
- **Token 取得**：`cat ~/kg/lab/claude-code-gateway/.env | grep CCG_API_TOKEN`（本地同步版本）。
- **第三方來源**：本目錄從 upstream snapshot 而來。原則上不改 `src/` Python 程式碼（要改行為請在 KG 側 wrapper），但 ops 殼層（Dockerfile/compose/env/pyproject）允許本地調整。

## 相對 upstream snapshot 的本地修改

`src/` Python 程式碼未動（與 2025-04-12 upstream 一致）。ops 殼層差異：

- **port 8080 → 8090**：`Dockerfile`（`EXPOSE`）、`docker-compose.yml`、`.env`（`CCG_PORT`）。避開 host 其他 8080 服務。
- **`CCG_DEFAULT_MODEL`**：`.env` 從 `claude-sonnet-4-20250514`（pinned date 版本）改為 `sonnet` alias，讓 CLI 自動解析最新版。
- **`docker-compose.yml` hardening**：加 `restart: unless-stopped`；`~/.claude.json` 掛載註解明示**不可 `:ro`**（CLI 會回寫 refresh OAuth token，`:ro` 會讓 CLI silently 失敗、輸出空字串）。
- **API auth 啟用**：`.env` 設定 `CCG_API_TOKEN`。auth 機制為上游內建（`src/config.py:11` + `src/main.py:29-32`），本地僅啟用為公開部署所需。
- **`pyproject.toml` build-backend**：commit `8853760` 修正為 `setuptools.build_meta`（snapshot 內 backend 字串非 PEP 517 標準）。

## 相關文檔

- Host / service map：`docs/reference/host_topology.md`
- Caddy 故障排查（含 `/claude/*` 遺失症狀）：`docs/sop/debug.md`
