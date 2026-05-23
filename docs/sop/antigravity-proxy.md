<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - lab/antigravity-proxy/
verified_against: 57f744f
-->
# Antigravity Proxy（純本地執行）

本機 **Google Antigravity 訂閱 → OpenAI-compatible API** 閘道。把多個 Google Pro AI Premium 帳號的 OAuth 配額池化，在 `localhost:3000` 暴露 `/v1/chat/completions`，供本機個人實驗工具（OpenClaw、CLI、實驗 script）以 `openai` SDK 直接取得 Claude / Gemini / GPT-OSS 模型，不消耗付費 API 額度。

> **2026-05-23 撤出公網**：原 `wordnexus.lol/ag/*` 路由與 VPS 容器已停用、Caddy handle 已移除。原因見〈封號風險〉段。現僅在本機 `bun run start` 跑，沒有任何遠端 endpoint。

定位上獨立於 KG：純粹個人 LLM PaaS。Podcast pipeline 等 KG 內部流程**不呼叫**此 proxy（pipeline 直接 subprocess 本機 `claude` CLI）。

> Upstream: [`frieser/antigravity-proxy`](https://github.com/frieser/antigravity-proxy)（v0.7.0，2026-02-23 snapshot；TypeScript + Bun）。直接 HTTP 打 Google 內部 Antigravity sandbox endpoint，不 subprocess CLI。
>
> **ToS 灰區**：upstream README 自註違反 Google 訂閱條款。多帳號池化即使在本機跑，仍違反 ToS。**僅供個人使用**，不要綁 daily-driver Google 帳號（見〈封號風險〉）。

## 部署事實

| key | value |
|-----|-------|
| 本地路徑 | `lab/antigravity-proxy/`（vendored；`.gitignore` 擋 `.venv/` / `.env` / `antigravity-accounts.json` / `data/*.json`） |
| 啟動方式 | `cd lab/antigravity-proxy && bun run start` |
| Bind | `http://127.0.0.1:3000`（localhost only，不對外） |
| 帳號池檔 | `lab/antigravity-proxy/antigravity-accounts.json`（含 refresh token，**不在 git**） |
| 帳號池在線 | 2（`max970228@gmail.com` + `maxn970228@gmail.com`） |
| Dashboard | `http://localhost:3000/frontend/index.html`（無需 auth，因為已 bind localhost） |
| 遠端 | **無**（VPS 容器已撤，Caddy `/ag/*` handle 已移除） |

## 封號風險（為什麼撤出公網）

按 wave 1（2026-02）/ wave 2（2026-03）/ wave 3（2026-05+）三波 Google Antigravity ban wave 的實證 pattern：

- **多帳號共用單一 ASN/IP**（VPS 公網 IP）= wave 1 主因
- **公網 OAuth gateway shape**（Bearer + reverse proxy）= wave 2 / 3 抓的形狀
- **UA fingerprint 偽裝** = 反指標（誠實 stale client 反而較不可疑）

撤回本機後 profile 從「小型 reseller」降到「個人多裝置」：流量極低、無公網暴露、refresh 行為與 desktop binding 接近。**6 個月 ban 機率估計從 ~60% → ~20%。** 完整威脅模型與 mitigation 性價比表見對話歷史中的「Antigravity Proxy 封號風險評估」段（agent report）。

**鐵則**：進池的 Google 帳號**假設會死**。不要用主 Gmail 的 Pro 訂閱進池；現役 `max970228` / `maxn970228` 為實驗用獨立帳號。

### 模型清單

`/v1/models` 回傳全 15 個註冊 ID。實測可用性分三檔：

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

## 使用方式（OpenAI SDK，本機）

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:3000/v1",
    api_key="dummy",  # localhost bind 無 auth，任意字串
)
resp = client.chat.completions.create(
    model="claude-opus-4-6-thinking",
    messages=[{"role": "user", "content": "..."}],
    stream=True,
)
```

OpenClaw / Cursor / Aider / Continue.dev：base URL `http://localhost:3000/v1`。

**出差時手機要打怎麼辦**：起 Tailscale / WireGuard，把筆電的 `localhost:3000` 透過 mesh VPN 暴露給其他裝置。**不要**再放 Caddy 公網。

## 即時 quota / health 監控（本機）

| 端點 | 用途 |
|---|---|
| `http://localhost:3000/frontend/index.html` | Web dashboard（GUI） |
| `http://localhost:3000/api/status` | REST JSON：每帳號 11 個 quota 群組 + healthScore + fingerprint |
| `http://localhost:3000/api/sse` | Server-Sent Events 即時推 |

> ⚠️ `/api/status` 回應**含 OAuth refresh / access token 明文**。localhost 不外露所以可接受；放上公網絕對不行（這也是撤出公網理由之一）。

**注意 `healthScore` 不是 Google 配額**：那是 frieser 本地對「最近失敗率」的內部評分。實際 Google 配額看 `quota[].quotaLeft`。

## 運維注意

- **新增 / 移除帳號**：本機 `bun run start` 跑 OAuth flow（upstream redirect 寫死 `localhost:3000`），完成後 token 自動寫 `antigravity-accounts.json`。
- **第三方來源**：本目錄從 upstream snapshot 而來；`src/` 程式碼除下述 UA patch 外未動。
- **舊 VPS 殘留**：`~/antigravity-proxy/data/` 在 VPS 上仍存在（含 refresh token）。若確認永不回退，應 `ssh ... 'rm -rf ~/antigravity-proxy'` 清除。

## 相對 upstream snapshot 的本地修改

- **`src/utils/headers.ts:18`**：`ANTIGRAVITY_VERSION` 從 `1.15.8` 改 `1.23.2`。Google 在 2026-05-19 Antigravity 2.0 發布後拒絕 1.15.8 UA。1.23.2 為 [`Wei-Shaw/sub2api`](https://github.com/Wei-Shaw/sub2api) 已驗證可用值。
  - ⚠️ **UA 偽裝是封號風險反指標**。撤回本機後 ban scoring 已降低，但這個 patch 還是會增加 fingerprint 異常分數。Google 再切版時可考慮直接還原並接受 stale-client 錯誤。
- **`docker-compose.yml`**：snapshot 保留，目前**不使用**（純本機 bun 直跑）。
- **`.env`**：只保留 upstream 預設（`BASE_URL` + `SAFETY_THRESHOLD=BLOCK_NONE`）。

## 維運常用指令

```bash
# 啟動
cd ~/kg/lab/antigravity-proxy && bun run start

# 背景啟動
cd ~/kg/lab/antigravity-proxy && (bun run start > /tmp/ag.log 2>&1 &)

# 查 process / 停止
lsof -ti :3000 | xargs kill   # 或 pkill -f "bun run src/server.ts"

# 看 log
tail -f /tmp/ag.log

# 健康檢查
curl -s http://localhost:3000/v1/models | jq '.data | length'   # 應為 15
curl -s http://localhost:3000/api/status | jq '.accounts[].email'
```

## 退場條件

以下任一觸發時應評估「停止維護」：

1. Google 再切 Antigravity 版本檢查策略，社群 wrapper 一個月內無 patch
2. 自己的 Google Pro 帳號被異常偵測警告或封禁（不分 product-scoped / full-account）
3. Antigravity SDK（I/O 2026 推出的合法路徑）對個人實驗的 per-run cost 已可接受

退場 = 刪 `lab/antigravity-proxy/` 目錄。不需要 migration 因為**沒有 KG 內部 caller**。

## 相關文檔

- Host / service map：`docs/reference/host_topology.md`（**SoT**；已移除 `/ag/*` 項目）
- 姊妹 proxy（Claude 訂閱 → API）：`docs/sop/claude-gateway.md`
