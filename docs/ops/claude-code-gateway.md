# Claude Code Gateway

KG workspace 的 **Claude subscription → OpenAI-compatible API** 閘道。將本機登入的 Claude Code CLI 包成 `/v1/chat/completions`，供 lab 端 PoC（podcast architect 等）直接用 `openai` SDK 呼叫 Claude 模型，不走 Anthropic API（無 per-token 費用，走訂閱額度）。

> Upstream: `enescingoz/claude-code-gateway`（third-party，透過 subprocess 呼叫 `claude` CLI；未抽取 OAuth token，但仍在 Anthropic 訂閱條款灰區，use at your own risk）。

## 部署事實

| key | value |
|-----|-------|
| 本地路徑 | `lab/claude-code-gateway/`（.gitignore，不入 git） |
| 遠端路徑 | `ubuntu@13.193.212.134:~/claude-code-gateway/` |
| 公網 endpoint | `https://wordnexus.lol/claude/v1` |
| 容器名 | `claude-code-gateway-api-1` |
| 內部 port | `8090` |
| Caddy 路由 | `/claude/*` → strip prefix → `localhost:8090` |
| 認證 | Bearer token（`.env` 的 `CCG_API_TOKEN`） |
| Docker volumes | `~/.claude` + `~/.claude.json`（主機 CLI 登入態） |
| 模型別名 | `sonnet` / `opus` / `haiku`（CLI 自動解析最新版） |

## Caddy 片段（事實來源：`docs/ops/BACKGROUND.md`）

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

現行呼叫點：`lab/podcast_architect_poc.py`（book → production plan）。

## 運維注意

- **登入態由主機 CLI 持有**：部署首次需在遠端主機 `claude` 互動登入，容器透過掛載 `~/.claude` 繼承。續訂或帳號換人需重新登入。
- **容器獨立於 KG API**：`knowledge-graph-api`（8000）與 `claude-code-gateway-api-1`（8090）互不依賴，smart deploy 只動 KG API。Gateway 更新需單獨 `docker compose up --build -d` 於遠端 `~/claude-code-gateway/`。
- **Token 取得**：`cat ~/kg/lab/claude-code-gateway/.env | grep CCG_API_TOKEN`（本地同步版本）。
- **第三方來源**：本目錄從 upstream clone，不做 fork 修改。要改行為請在 KG 側 wrapper，不要改 gateway 原始碼。

## 相關文檔

- Host / service map：`docs/ops/BACKGROUND.md`
- Caddy 故障排查（含 `/claude/*` 遺失症狀）：`docs/dev/debug.md`
