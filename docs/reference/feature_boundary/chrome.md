<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - chrome-extension/
verified_against: 80147399
-->
# Chrome Extension Feature Boundary

KG Chrome extension（`KG 詞彙助手`, Manifest V3）— 網頁閱讀選詞 → 翻譯 → 寫入用戶詞庫，與 iOS app 共用 backend (`wordnexus.lol`)。

## 檔案清冊

### Entry Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `manifest.json` | — | MV3 manifest：`activeTab` / `sidePanel` / `storage` 權限，`host_permissions` 限 `wordnexus.lol/*` |
| `background.js` | 101 | Service worker：sidepanel 開關、訊息路由、token 注入 |

### Content Script Layer（網頁注入）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `content/content.js` | 502 | 選詞偵測、popup 顯示、選取範圍管理；與 sidepanel 透過 `chrome.runtime.sendMessage` 溝通；href 渲染走 `shared/pure.js safeUrl()`；popup 注入 closed Shadow DOM 並設 `data-theme` 令 token 生效 |
| `content/popup.css` | — | popup 樣式（tokens.css 子集） |

### Sidepanel Layer（主 UI）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `sidepanel/index.html` | — | sidepanel 入口 |
| `sidepanel/app.js` | 410 | UI 主邏輯：翻譯結果展示、加入詞庫、登入態管理；href 渲染走 `shared/pure.js safeUrl()` |
| `sidepanel/styles.css` | — | sidepanel 樣式 |

### Options Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `options/options.html` | — | 設定頁面 |
| `options/options.js` | 138 | 設定持久化（`chrome.storage`） |
| `options/options.css` | — | 設定頁樣式 |

### Shared Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `shared/api.js` | 219 | `wordnexus.lol` HTTP client + auth header |
| `shared/pure.js` | 348 | 無副作用 helpers（字串處理、選詞 boundary、token 解析、`safeUrl()` URL scheme allowlist） |
| `shared/pure.test.js` | 450 | `pure.js` 單元測試 |
| `shared/theme.js` | 44 | 深淺色主題切換 |
| `shared/tokens.css` | — | 設計 token（**生成檔**，由 `ops/gen_web_tokens.py` 從 `design-system/tokens.json` 產出，禁手改；`:root, :host` selector 供 closed Shadow DOM 生效） |
| `shared/fonts.css` | — | surface-local `@font-face`（woff2 URL；font *family* 為 tokens.css 的 `--font-*` token，URL 各 surface 自帶） |

## 對外契約

- **Backend endpoints**：見 [`docs/reference/tech_index.md`](../tech_index.md) 對應 router 章節。Chrome 不維護自己的 endpoint 表。
- **Auth**：與 iOS 共享 Google / Apple 登入 backend；token 存 `chrome.storage.local`。
- **Domain 白名單**：`host_permissions` 只放 `wordnexus.lol/*`，新 backend domain 變動需同步 `manifest.json`。
- **URL scheme allowlist（XSS defense-in-depth）**：sidepanel / content 渲染外部 href 一律走 `shared/pure.js safeUrl()`；僅放行 `http:` / `https:` / `chrome-extension:`，其餘（`javascript:` / `data:` / `vbscript:` / `file:` / `blob:` 等）一律 fallback `#`。

## 不在 scope 內

- iOS 端 SwiftData、SwiftUI、podcast、reader 模組 → 走 [`vocabulary.md`](vocabulary.md) / [`reader.md`](reader.md) / 等。
- Backend FastAPI router 實作 → [`tech_index.md`](../tech_index.md)。

## 變動時要做的事

| 動作 | 同 PR 同步 |
|------|-----------|
| 改 manifest 權限或 host 白名單 | 本檔「Entry Layer」段 + [`docs/reference/product_surface.md`](../product_surface.md) 對應 bullet |
| 新增 / 刪除主要 JS 檔案 | 本檔對應 Layer 表 |
| 改 `shared/api.js` 呼叫的 backend endpoint | [`tech_index.md`](../tech_index.md) router 章節 |
| 改認證流程 | [`docs/sop/architecture.md`](../../sop/architecture.md) auth 段 |
| 改設計 token / 配色 | 改 `design-system/tokens.json` 再跑 `ops/gen_web_tokens.py` 重生 `shared/tokens.css`（禁直接手改生成檔；drift 由 `ops/token_drift_check.py` 守） |
