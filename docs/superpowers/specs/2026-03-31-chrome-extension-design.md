# KG Chrome Extension — Design Spec

## Product Goal

將 iOS app 的核心價值鏈（選詞 → 翻譯/解釋 → 詞彙庫）帶到 Chrome 瀏覽器，外觀與 iOS app 完全一致。

## Scope

### In Scope
- 選詞 Popup：選取文字 → 浮出翻譯/解釋 → 一鍵加詞（帶網頁 context）
- Side Panel：詞彙列表 + 搜尋 + 點擊詳情
- 三主題：Light / Dark / Sepia，1:1 映射 iOS design token
- 字型內嵌：Athelas、ElmsSans、CormorantGaramond（woff2），中文靠 macOS 系統字型
- 網頁登入頁 + JWT token 管理
- Backend：source 結構化欄位 + CORS 調整

### Out of Scope
- Graph view（力導向圖）
- Notebook 管理、批次操作、複習功能
- 跨平台（Windows/Linux）字型 fallback
- Mochi 匯出

## Target Platform
- macOS Chrome (Manifest V3)

---

## Architecture

```
chrome-extension/
├── manifest.json              ← Manifest V3, permissions: activeTab, sidePanel, storage, identity
├── background.js              ← service worker: auth token 管理、API proxy
├── content/
│   ├── content.js             ← 注入所有頁面，監聽 mouseup 選取事件
│   └── popup.js + popup.css   ← Shadow DOM 內的浮動翻譯 popup
├── sidepanel/
│   ├── index.html
│   ├── app.js                 ← 詞彙列表、搜尋、詳情
│   └── styles.css
├── login/
│   └── callback.html          ← OAuth 回調，接收 token 存入 chrome.storage
├── options/
│   └── options.html           ← 主題切換、登出、帳號狀態
├── shared/
│   ├── tokens.css             ← iOS design token → CSS custom properties
│   ├── api.js                 ← Backend API client（translate, vocab, auth）
│   └── theme.js               ← 主題切換：讀寫 chrome.storage，套用 data-theme attribute
└── fonts/
    ├── Athelas-Regular.woff2
    ├── Athelas-Bold.woff2
    ├── ElmsSans-Regular.woff2
    ├── ElmsSans-Bold.woff2
    └── CormorantGaramond-Italic.woff2
```

### Shadow DOM 隔離

Content script 注入的 popup UI 包在 Shadow DOM 中：
- Extension CSS 不洩漏到網頁
- 網頁 CSS 不污染 extension UI
- 字型透過 Shadow DOM 內的 `@font-face` 載入

### 通訊架構

```
content.js  ──message──>  background.js  ──fetch──>  Backend API
                              │
sidepanel/app.js ──message──> │
                              │
options.html ──chrome.storage──> 共享設定（theme, token）
```

---

## User Flows

### Flow 1: 首次安裝 & 登入

1. 安裝 extension → 自動開啟 options 頁
2. 點「登入」→ 開新 tab 至 `wordnexus.lol/login`
3. 使用者選 Google 或 Apple 登入
4. OAuth 完成 → 頁面呼叫 `chrome.runtime.sendMessage` 把 JWT token 傳回 background.js
5. background.js 存 token 至 `chrome.storage.local`
6. Options 頁顯示已登入狀態

### Flow 2: 選詞翻譯 & 加詞

1. 使用者在任意網頁選取文字
2. content.js 偵測 `mouseup` + `window.getSelection()`
3. 判斷選取文字長度（1-200 字元），符合條件則：
   - 擷取 context：選取文字周圍的完整句子
   - 擷取 source：`document.title` + `location.href`
   - 顯示 Shadow DOM popup，初始狀態 loading
4. 透過 background.js 呼叫 API：≤50 字元 → `POST /api/translate/quick`，>50 字元 → `POST /api/translate/phrase`
5. Popup 顯示翻譯結果：word、pronunciation、POS、translation
6. 點「展開」→ 呼叫 `POST /api/translate/explain` 顯示語境解釋
7. 點「加入詞彙」→ `POST /api/vocab` body: `[{word, translation, context, root_form, source: {type:"web", title, url}}]`
8. 按鈕變為「已加入」徽章（success 色）
9. 點 popup 外部或按 Esc → dismiss

### Flow 3: Side Panel 瀏覽

1. 點 extension toolbar icon → 開啟 side panel
2. 載入時 `GET /api/vocab` 取得詞彙列表
3. 列表顯示：word、POS、translation、source icon（web/book）
4. 搜尋欄輸入 → debounce 300ms → 前端過濾（word + translation）
5. 點擊詞彙 → 展開詳情：翻譯、詞性、例句、context 句子、來源（可點擊 URL）
6. 下拉刷新或自動定時刷新

### Flow 4: 主題切換

1. 在 options 頁或 side panel header 切換 light/dark/sepia
2. 寫入 `chrome.storage.local`
3. 所有 extension UI（popup、side panel、options）監聽 storage change → 即時套用
4. Content script popup 同步更新

---

## Design Token Mapping (iOS → CSS)

### Colors

```css
/* Light */
[data-theme="light"] {
  --page-bg: #F3F3F1;
  --stage-bg: #F8F7F6;
  --card-bg: #FCFCFA;
  --text-primary: #30302E;
  --text-secondary: #6E6E6B;
  --text-tertiary: #70706B;
  --accent: hsl(215, 28%, 66%);
  --success: hsl(152, 20%, 60%);
  --destructive: hsl(355, 26%, 66%);
  --warning: hsl(36, 80%, 80%);
  --tint: hsl(215, 16%, 52%);
}

/* Dark */
[data-theme="dark"] {
  --page-bg: #1A1B1D;
  --stage-bg: #202124;
  --card-bg: #28292C;
  --text-primary: #F0F0EB;
  --text-secondary: #BDBFC4;
  --text-tertiary: #9499A3;
  --accent: hsl(215, 28%, 70%);
  --success: hsl(152, 20%, 62%);
  --destructive: hsl(355, 25%, 68%);
  --warning: hsl(36, 60%, 90%);
  --tint: hsl(215, 18%, 74%);
}

/* Sepia */
[data-theme="sepia"] {
  --page-bg: #F5F1EB;
  --stage-bg: #FAF6F0;
  --card-bg: #FCFAF6;
  --text-primary: #30302E;
  --text-secondary: #6E6E6B;
  /* accent/success/destructive 同 light */
}
```

### Typography

```css
:host {
  --font-serif: 'Athelas', 'STSongti TC', 'Noto Serif TC', Georgia, serif;
  --font-sans: 'ElmsSans', 'PingFang TC', -apple-system, sans-serif;
  --font-italic: 'CormorantGaramond', 'Georgia', serif;
  --font-mono: 'ElmsSans Mono', 'SF Mono', monospace;

  --text-h1: 28px;
  --text-h2: 22px;
  --text-section-title: 18px;
  --text-body: 17px;
  --text-subhead: 15px;
  --text-caption: 12px;
  --text-caption2: 11px;
  --text-detail-word: 27px;
  --text-row-word: 18px;
}
```

### Spacing & Radii

```css
:host {
  --sp-micro: 2px;
  --sp-tiny: 3px;
  --sp-xs: 4px;
  --sp-sm: 8px;
  --sp-compact: 12px;
  --sp-md: 16px;
  --sp-lg: 24px;
  --sp-xl: 32px;
  --sp-xxl: 48px;

  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-card: 12px;
  --radius-overlay: 13px;
  --radius-chip: 8px;

  --card-padding: 18px;
  --section-gap: 14px;
  --inline-gap: 8px;
  --sheet-padding: 24px;
  --page-h-padding: 20px;
}
```

### Motion

```css
:host {
  --ease-quick: ease-out 0.15s;
  --ease-control: ease-out 0.14s;
  --ease-chip: ease-out 0.18s;
  --spring-standard: cubic-bezier(0.25, 0.46, 0.45, 0.94) 0.3s;
  --spring-emphasized: cubic-bezier(0.25, 0.46, 0.45, 0.94) 0.35s;
  --transition-content-swap: opacity 0.2s ease-out, transform 0.2s ease-out;
  --transition-panel-reveal: transform 0.3s ease-out, opacity 0.25s ease-out;
}
```

---

## Component Mapping (iOS → Chrome)

| iOS Component | Chrome 對應 | 用途 |
|---|---|---|
| TranslationPanel | content/popup | 選詞浮動翻譯 |
| VocabToneChip | `.kg-chip` | 詞性標籤 |
| AppActionButton | `.kg-btn` | 「加入詞彙」按鈕 |
| VocabListCard | `.kg-list-card` | Side panel 詞彙列表項 |
| AppSearchField | `.kg-search` | Side panel 搜尋欄 |
| WordDetailSheet | `.kg-detail` | Side panel 詞彙詳情（inline 展開） |
| AppSectionCard | `.kg-section-card` | Side panel 分區容器 |
| VocabSceneShell | side panel root | 4-state container（loading/empty/error/content） |

---

## Backend Changes

### 1. VocabEntry Source 欄位

新增 optional `source` JSON 欄位：

```python
# schema
class VocabSource(BaseModel):
    type: Literal["book", "web"]
    title: str | None = None
    url: str | None = None       # web only
    chapter: str | None = None   # book only

# VocabEntry 新增
source: VocabSource | None = None
```

- 後端使用 SQLite（CardStore, SQLModel）。需 migration 新增 nullable source JSON column
- POST /api/vocab request body（VocabEntry schema）新增 `source` 欄位
- GET /api/vocab response（CardResponse schema）新增 `source` 欄位
- 向後相容：現有資料 source = null，讀取時自動容忍缺失

### 2. CORS

```python
# settings.py CORS_ORIGINS 新增
"chrome-extension://<extension-id>"
```

或更靈活：允許所有 `chrome-extension://` origin（開發階段），production 鎖定特定 ID。

### 3. Web OAuth Flow（新增子系統）

目前後端只有 `POST /auth/verify`（接收 iOS 端已完成的 provider token）。Chrome extension 需要完整的 server-side OAuth：

**Google:**
- `GET /auth/google/login` → redirect 到 Google OAuth consent screen
- `GET /auth/google/callback` → 接收 authorization code → exchange for id_token → 呼叫既有 verify 邏輯 → 回傳含 JWT 的 HTML 頁面
- 頁面透過 `chrome.runtime.sendMessage(extensionId, {token})` 傳回 extension

**Apple:**
- `GET /auth/apple/login` → redirect 到 Apple Sign-In web flow
- `POST /auth/apple/callback` → 接收 authorization code → validate → 回傳含 JWT 的 HTML 頁面

**Extension 端:**
- manifest.json `externally_connectable` 設定允許 `wordnexus.lol` 發送 message
- background.js 監聽外部 message，存 token 至 chrome.storage

**Fallback:** 頁面顯示 JWT token + 複製按鈕（extension 未安裝時）

---

## State Management

### chrome.storage.local

```json
{
  "auth_token": "jwt...",
  "user_id": "...",
  "theme": "light" | "dark" | "sepia",
  "last_sync": 1711843200
}
```

### Side Panel 狀態

```
state: "loading" | "empty" | "error" | "content"
vocabList: VocabCard[]
searchText: string
expandedCardId: string | null
```

### Popup 狀態

```
state: "loading" | "translated" | "saved" | "error"
word: string
translation: string
pronunciation: string
pos: string
explanation: string | null
source: { type: "web", title: string, url: string }
```

---

## Error Handling

| 情境 | 行為 |
|---|---|
| 未登入 | Popup 顯示「請先登入」+ 按鈕開 options |
| Token 過期 | 自動清除 token，顯示重新登入提示 |
| API 失敗 | Popup/Side panel 顯示 error state + 重試按鈕 |
| 無選取文字 | 不觸發 popup |
| 選取 >50 字元 | 走 phrase 翻譯而非 quick |
| 選取 >200 字元 | 不觸發 popup |
| 離線 | 顯示離線提示，side panel 用 cached data |

---

## Security

- JWT token 存 `chrome.storage.local`（extension-only 存取）
- API 呼叫全部透過 background.js（避免 content script 直接持有 token）
- Content script 只透過 `chrome.runtime.sendMessage` 與 background 通訊
- Shadow DOM 隔離防止 host page 存取 extension DOM
- CSP: 遵循 Manifest V3 預設（禁止 inline script、eval）
