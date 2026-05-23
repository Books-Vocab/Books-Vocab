<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - lab/antigravity-proxy/
verified_against: 3e0de58
-->
# Antigravity Proxy

KG host 的 **Google Antigravity 訂閱 → OpenAI-compatible API** 閘道。把多個 Google Pro AI Premium 帳號的 OAuth 配額池化，透過 `/v1/chat/completions` 對外暴露，供 KG 以外的個人實驗工具（OpenClaw、出差時 mobile 呼叫等）直接用 `openai` SDK 取得 Claude / Gemini / GPT-OSS 模型，不消耗付費 API 額度。

定位上**獨立於 KG**：物理寄生於同主機（KG VPS），邏輯上是個人 LLM PaaS。Podcast pipeline 等 KG 內部流程**不呼叫**此 proxy（pipeline 直接 subprocess 本機 `claude` CLI）。

> Upstream: [`frieser/antigravity-proxy`](https://github.com/frieser/antigravity-proxy)（v0.7.0，2026-02-23 snapshot；30⭐ TypeScript + Bun + Docker）。直接 HTTP 打 Google 內部 Antigravity sandbox endpoint，不 subprocess CLI。
>
> **ToS 灰區**：upstream README 自註違反 Anthropic / Google 訂閱條款。多帳號輪換 + 公網暴露提高 Google 反濫用偵測風險。**僅供個人 + 信任的人使用**，避免綁 daily-driver Google 帳號。

## 部署事實

| key | value |
|-----|-------|
| 本地路徑 | `lab/antigravity-proxy/`（vendored；`.gitignore` 擋 `.venv/` / `.env` / `data/*.json`） |
| 遠端路徑 | `ubuntu@13.193.212.134:~/antigravity-proxy/` |
| 公網 endpoint | `https://wordnexus.lol/ag/v1` |
| 容器名 | `antigravity-proxy-proxy-1` |
| 內部 port | `3000` |
| Caddy 路由 | `/ag/*` → strip prefix → `localhost:3000`（Bearer header check） |
| 認證 | Caddy 層 Bearer token 比對；token 存在 host `/etc/caddy/Caddyfile`（不在 git） |
| Docker volumes | `./data:/app/data:z`（mount accounts + config JSON） |
| 帳號池在線 | 2（`max970228@gmail.com` + `maxn970228@gmail.com`） |
| 規劃容量 | 3（第 3 個 Google Pro 待本機 OAuth + scp 同步） |
| Dashboard | `https://wordnexus.lol/ag/frontend/index.html`（需 Bearer） |

### 模型清單

`/v1/models` 回傳全 15 個註冊 ID（從 Antigravity sandbox endpoint cache 而來）。實測可用性分三檔：

**✅ 穩定可用**：

| 模型 ID | 等級 | 備註 |
|---|---|---|
| `claude-opus-4-6-thinking` | 旗艦 | reasoning trace 完整回傳 |
| `gemini-2.5-pro` | 旗艦 | |
| `gemini-3.1-pro-low` | 旗艦 | |
| `gemini-3.5-flash-low` | 主力 | I/O 2026 發布；`-medium` / `-high` 在 quota 帳簿可見但 inference endpoint 對 OAuth 訂閱戶不開放 |
| `gemini-3-flash` / `gemini-3-flash-agent` | 中堅 | |
| `gemini-2.5-flash` / `gemini-2.5-flash-lite` | 入門 | |
| `gemini-3.1-flash-lite` | 入門 | |
| `gpt-oss-120b-medium` | OpenAI 系 | OpenAI 的 gpt-oss 透過 Google 提供 |

**⚠️ 間歇 / 配額敏感**：

| 模型 ID | 症狀 |
|---|---|
| `claude-sonnet-4-6` | 配額有限，密集打容易 `quota_exhausted`；reset 後恢復 |
| `gemini-3.1-pro-high` | sandbox endpoint 對 OAuth 訂閱戶間歇 403 |

**❌ Cached 但對 OAuth 訂閱戶不開放**（看得到打不通）：

| 模型 ID | 擋的位置 |
|---|---|
| `gemini-2.5-flash-thinking` | 403 `unknown_error` |
| `gemini-3.1-flash-image` | 403 `unknown_error` |
| `gemini-pro-agent` | 403 `unknown_error` |

每帳號 11 個 quota 群組，**5 小時 rolling window** reset。

## Caddy 片段（事實來源：`docs/reference/host_topology.md`）

```caddy
wordnexus.lol {
    handle /claude/* { ... reverse_proxy localhost:8090 }
    handle /ag/* {
        @authed header Authorization "Bearer <CADDY_AG_TOKEN>"
        handle @authed {
            uri strip_prefix /ag
            reverse_proxy localhost:3000
        }
        respond 401
    }
    reverse_proxy localhost:8000
}
```

修改 Caddyfile 必須**保留 `/ag/*` handle 與 Bearer 比對**，且 handle 順序需在 catch-all `reverse_proxy localhost:8000` **之前**，否則 `/ag/*` 會被 KG API 吃掉。

## 使用方式（OpenAI SDK）

```python
from openai import OpenAI
client = OpenAI(
    base_url="https://wordnexus.lol/ag/v1",
    api_key="<CADDY_AG_TOKEN>",  # 從 host Caddyfile 取
)
resp = client.chat.completions.create(
    model="claude-opus-4-6-thinking",   # 或上表任一可用 model
    messages=[{"role": "user", "content": "..."}],
    stream=True,
)
```

OpenClaw / Cursor / Aider / Continue.dev 等 OpenAI-compatible 工具：把 base URL 指到 `https://wordnexus.lol/ag/v1`，API key 填 Caddy Bearer token 即可。

## 即時 quota / health 監控

| 端點 | 用途 |
|---|---|
| `https://wordnexus.lol/ag/frontend/index.html` | Web dashboard（GUI） |
| `https://wordnexus.lol/ag/api/status` | REST JSON：每帳號 11 個 quota 群組 + healthScore + fingerprint |
| `https://wordnexus.lol/ag/api/sse` | Server-Sent Events 即時推（每次請求結束 push 帳號狀態） |

**注意 `healthScore` 不是 Google 配額**：那是 frieser 本地對「最近失敗率」的內部評分，會在 routing 時避開低分帳號。實際 Google 配額看 `quota[].quotaLeft`。

## 運維注意

- **OAuth 帳號池在 host `~/antigravity-proxy/data/`**：`antigravity-accounts.json`（含 refresh token）+ `config.json`。**不在 git**。新增 / 移除帳號需本機 `bun run start` 跑 OAuth flow，再 `scp` 同步 JSON 上去 + `docker compose restart`。
- **OAuth redirect 寫死 `localhost:3000`**（upstream issue #8）：故所有帳號**必須在本機登入**，VPS 不能直接 OAuth；登好把 JSON 傳上去。
- **`config.json` EACCES 警告**（upstream issue #9）：container 啟動會嘗試寫 `/app/config.json`（root-owned），失敗後 fallback 用 defaults。**不影響功能**，accounts 仍從 `/app/data/` 正常 load。
- **容器獨立於 KG API**：`knowledge-graph-api`（8000）/ `claude-code-gateway-api-1`（8090）/ `antigravity-proxy-proxy-1`（3000）三者互不依賴。Gateway 更新需單獨 `cd ~/antigravity-proxy && docker compose up -d --build`。`devops_kg_safe.sh` **不涵蓋**此 proxy。
- **Bearer token 取得**：`ssh ubuntu@... 'sudo grep Bearer /etc/caddy/Caddyfile'`。token 外洩需立刻：(a) 改 Caddyfile 新值，(b) `sudo systemctl reload caddy`。
- **第三方來源**：本目錄從 upstream snapshot 而來；`src/` 程式碼除下述 UA patch 外未動，ops 殼層（Dockerfile/compose/env）允許本地調整。

## 相對 upstream snapshot 的本地修改

- **`src/utils/headers.ts:18`**：`ANTIGRAVITY_VERSION` 從 `1.15.8` 改 `1.23.2`。Google 在 2026-05-19 Antigravity 2.0 發布後拒絕 1.15.8 的 UA（回 `"This version of Antigravity is no longer supported"`）；1.23.2 為 [`Wei-Shaw/sub2api`](https://github.com/Wei-Shaw/sub2api) 5/11 commit 已驗證可用值。Google 再切版時改此常數即可。
- **`docker-compose.yml`**：升級為 `restart: unless-stopped`；volumes 對齊 `./data:/app/data:z`。
- **`data/` 權限**：host 上 `chmod 777` 繞 upstream issue #9。
- **`.env`**：只保留 upstream 預設（`BASE_URL` + `SAFETY_THRESHOLD=BLOCK_NONE`）。

## 維運常用指令

```bash
# 看 container 狀態
ssh -i ~/.ssh/lightsail_default.pem ubuntu@13.193.212.134 'docker ps --filter name=antigravity'

# 看 log（最近 50 行）
ssh -i ~/.ssh/lightsail_default.pem ubuntu@13.193.212.134 \
  'docker logs --tail 50 antigravity-proxy-proxy-1'

# 重啟（不重 build）
ssh -i ~/.ssh/lightsail_default.pem ubuntu@13.193.212.134 \
  'cd ~/antigravity-proxy && docker compose restart'

# 改完 UA / Dockerfile 後重 build
ssh -i ~/.ssh/lightsail_default.pem ubuntu@13.193.212.134 \
  'cd ~/antigravity-proxy && docker compose up -d --build'

# 同步本機帳號池檔到 VPS
rsync -av -e "ssh -i ~/.ssh/lightsail_default.pem" \
  ~/kg/lab/antigravity-proxy/data/ \
  ubuntu@13.193.212.134:~/antigravity-proxy/data/
ssh -i ~/.ssh/lightsail_default.pem ubuntu@13.193.212.134 \
  'cd ~/antigravity-proxy && docker compose restart'
```

## 退場條件

以下任一觸發時應評估「停止維護 / 改用付費 API」：

1. Google 再切 Antigravity 版本檢查策略，社群 wrapper 一個月內無 patch
2. 自己的 Google Pro 帳號被異常偵測警告或封禁
3. Antigravity SDK（I/O 2026 推出的合法路徑）對 podcast pipeline / 個人實驗的 per-run cost 已可接受

退場 = `docker compose down` + 從 Caddyfile 刪 `/ag/*` handle + 從 `lab/` 刪目錄。不需要 migration 因為**沒有 KG 內部 caller**。

## 相關文檔

- Host / service map：`docs/reference/host_topology.md`（**SoT**）
- Caddy 故障排查：`docs/sop/debug.md`
- 姊妹 proxy（Claude 訂閱 → API）：`docs/sop/claude-gateway.md`
