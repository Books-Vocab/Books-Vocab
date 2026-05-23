<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - lab/codex-gateway/
verified_against: 41bf8dd
-->
# Codex Gateway

本機 **ChatGPT Plus/Pro 訂閱 → OpenAI-compatible API** 閘道。把 ChatGPT 訂閱裡的 Codex（GPT-5.5 / GPT-5.4-codex 等）OAuth token 包成 `/v1/chat/completions` 與 `/v1/responses`，給 OpenClaw / Cursor / Aider / Continue / 本機實驗 script 直接用 `openai` SDK 取得，不消耗付費 API 額度。

定位**獨立於 KG**：純粹個人 LLM PaaS，與 KG backend 無內部 caller。對標 sister gateway：

- `lab/claude-code-gateway/` — Claude Max 訂閱
- `lab/antigravity-proxy/` — Google Pro 訂閱（已撤公網）
- **本 gateway** — ChatGPT Plus/Pro 訂閱

三者模型線互補：Claude Opus 4.6 / Gemini 3.1 Pro / GPT-5.5。

> Upstream: [`Soju06/codex-lb`](https://github.com/Soju06/codex-lb) **v1.19.0-beta.1**（2026-05-19 snapshot；FastAPI + uv，1.6k⭐）。讀取 Codex CLI 的 `~/.codex/auth.json`，轉打 OpenAI `/v1/responses`。
>
> **ToS 灰區**：OpenAI 已明文「不得分享帳號」。截至 2026-05 **無大規模封號實證**（僅有 `flagged-accounts` 軟降級至 `gpt-5.2`，見 [codex#12079](https://github.com/openai/codex/issues/12079)）。但**多帳號 + 公網**會主動發 ban 訊號，**僅限本機 / 單一個人帳號使用**。

## 部署事實

| key | value |
|-----|-------|
| 本地路徑 | `lab/codex-gateway/`（vendored；`.gitignore` 擋 `auth.json` / `*.db` / `data/` / `.venv/`） |
| 啟動方式 | `cd lab/codex-gateway && .venv/bin/codex-lb --host 127.0.0.1 --port 2455` |
| Bind | `http://127.0.0.1:2455`（localhost only，不對外）；upstream 另預留 `1455` admin/ws port — **本部署不啟用** |
| Dashboard | `http://127.0.0.1:2455/`（首次啟動 console print bootstrap token；localhost 連線免 token） |
| Data dir | `$CODEX_LB_DATA_DIR`（建議 `~/.codex-lb`；存 sqlite + encrypted token，**不在 git**） |
| 帳號池在線 | 0（待手動加；建議 1 個 ChatGPT Pro，不池化） |
| 遠端 | **無**（不上 VPS、不過 Caddy；學 antigravity-proxy 教訓） |

## 為什麼純本機

OpenAI 目前未發生 Google 級別 ban wave，但具備所有觸發條件：

- ToS 明文禁止帳號共用
- Codex CLI 已有 `flagged-accounts` 自動降級機制（軟封）
- 反濫用 ML 是 wave-based，先發訊號的會優先進名單

**鐵則**：
- 只放 1 個 ChatGPT 訂閱帳號（不要把 codex-lb 的 multi-account pool 開起來 — 它就是 ban 訊號的形狀）
- 不開公網 / 不過 Caddy / 不放 Tailscale 以外的 remote
- 進池的 ChatGPT 帳號**假設會被軟封**，不用 daily-driver Gmail 訂閱

## 帳號設置（首次）

ChatGPT 訂閱戶須先登入 Codex CLI 一次（自己的 macOS）：

```bash
codex auth login   # 開瀏覽器 OAuth；完成後 ~/.codex/auth.json 寫入 access_token + refresh_token + account_id
ls ~/.codex/auth.json   # 確認存在
```

然後在 codex-lb dashboard 加帳號（具體 UI 步驟依 upstream README / 實際介面為準，可能是匯入 `auth.json` 或貼 token）：

```bash
cd ~/kg/lab/codex-gateway && .venv/bin/codex-lb --host 127.0.0.1 --port 2455
# 開 http://127.0.0.1:2455 → Accounts → 依 UI 指示加入
```

## 使用方式（OpenAI SDK，本機）

### OpenCode / 任意 OpenAI-compatible client

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://127.0.0.1:2455/v1",
    api_key="dummy",        # 預設 localhost 不檢查 API key；要開 per-key rate limit 走 dashboard 簽發
)
resp = client.chat.completions.create(
    model="gpt-5.3-codex",   # ChatGPT Plus 訂閱實測唯一可用 model（2026-05-23）
    messages=[{"role": "user", "content": "..."}],
    stream=True,
)
```

> **模型權限注意**：ChatGPT **Plus** 訂閱只能呼叫 `gpt-5.3-codex`。其他 `gpt-5` / `gpt-5-codex` / `gpt-5.4-codex` / `gpt-5.1-codex` 等會回 `not supported when using Codex with a ChatGPT account`（即使 `/v1/models` 顯示出來）。升 Pro / Business / Enterprise 才有更廣範圍。

### Codex CLI 本身（讓 codex 用 codex-lb pool）

`~/.codex/config.toml`：

```toml
model = "gpt-5.3-codex"
model_reasoning_effort = "xhigh"
model_provider = "codex-lb"

[model_providers.codex-lb]
name = "OpenAI"
base_url = "http://127.0.0.1:2455/backend-api/codex"
wire_api = "responses"
supports_websockets = true
requires_openai_auth = true
```

## 退場條件

任一觸發即評估「停止維護」：

1. OpenAI 出現第一波公開的 ChatGPT-subscription Codex proxy ban wave（盯 [codex issues](https://github.com/openai/codex/issues) + reddit r/OpenAI）
2. 自己的 ChatGPT 帳號出現 `flagged-accounts` 自動降級（gpt-5.5 → gpt-5.2 fallback）
3. Codex CLI 升級導致 OAuth flow / response shape 大改，codex-lb 一個月內無 patch

退場 = 刪 `lab/codex-gateway/` 目錄。沒有 KG 內部 caller，無 migration 成本。

## 運維常用指令

```bash
# 啟動（前台）
cd ~/kg/lab/codex-gateway && .venv/bin/codex-lb --host 127.0.0.1 --port 2455

# 啟動（背景）
cd ~/kg/lab/codex-gateway && (CODEX_LB_DATA_DIR=$HOME/.codex-lb .venv/bin/codex-lb --host 127.0.0.1 --port 2455 > /tmp/codex-lb.log 2>&1 &)

# 健康檢查
curl -s http://127.0.0.1:2455/v1/models | jq '.data | length'

# 停止
pkill -f codex-lb

# 升級 upstream snapshot（手動）
cd /tmp && git clone --depth 1 https://github.com/Soju06/codex-lb.git
rsync -av --delete --exclude='.git' --exclude='.venv' /tmp/codex-lb/ ~/kg/lab/codex-gateway/
cd ~/kg/lab/codex-gateway && uv pip install -e .
```

## 相對 upstream snapshot 的本地修改

- **`.gitignore` 末段擴充**：加 `auth.json` / `codex-lb.db` / `/var/lib/codex-lb/` / `data/` 阻擋 runtime secrets 進 git
- **`app/` + `config/` 套件**：未修改（純 vendored；packages 定義見 `pyproject.toml` `[tool.hatch.build.targets.wheel]`）

## 相關文檔

- Host / service map：`docs/reference/host_topology.md`（**SoT**）
- 姊妹 gateway（Claude）：`docs/sop/claude-gateway.md`
- 姊妹 gateway（Antigravity）：`docs/sop/antigravity-proxy.md`
