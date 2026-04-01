# KG Chrome Extension Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 將 iOS app 核心功能（選詞翻譯、加詞、詞彙列表）帶到 Chrome，外觀完全一致。
**Architecture:** Chrome Extension (Manifest V3) + Shadow DOM popup + Side Panel + 復用現有 backend API。Backend 新增 source 欄位、CORS、Web OAuth flow。
**Tech Stack:** Chrome Extension Manifest V3, vanilla JS (no framework), CSS custom properties, SQLite migration, FastAPI

---

## Task 1: Backend — Card model source 欄位

**Files:**
- Modify: `backend/src/kg/api_models.py:23-35` (VocabEntry) + `:77-102` (CardResponse)
- Modify: `backend/src/kg/cards.py:24-51` (Card SQLModel) + `:95-121` (_migrate_review_columns)
- Modify: `backend/src/kg/vocab_service.py:104-139` (card_response builder) + `:510-517` (cards.add call)
- Test: `backend/tests/test_vocab_source.py`

- [ ] **Step 1: 寫 failing test**
```python
# backend/tests/test_vocab_source.py
"""Tests for the new VocabEntry.source field end-to-end."""
import json
from kg.api_models import VocabEntry, CardResponse

def test_vocab_entry_accepts_source():
    entry = VocabEntry(
        word="ephemeral", translation="短暫的",
        source={"type": "web", "title": "BBC News", "url": "https://bbc.com/article"}
    )
    assert entry.source is not None
    assert entry.source.type == "web"

def test_vocab_entry_source_optional():
    entry = VocabEntry(word="hello", translation="你好")
    assert entry.source is None

def test_card_model_has_source_column(tmp_path):
    from kg.cards import CardStore
    store = CardStore(tmp_path / "test.db")
    card = store.add(content="test", meaning="測試", source=json.dumps({"type": "web", "url": "https://example.com"}))
    assert card.source is not None
    retrieved = store.find_by_content("test")
    assert json.loads(retrieved.source)["type"] == "web"

def test_card_response_includes_source():
    resp = CardResponse(
        id="abc", content="test", meaning="m", pos=None,
        difficulty=None, difficultyTier=None, note=None,
        examples=[], mode="recognition", isDeleted=False,
        source={"type": "web", "title": "Test", "url": "https://example.com"}
    )
    assert resp.source.type == "web"
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_vocab_source.py -v`
Expected: FAIL (source field doesn't exist)

- [ ] **Step 3: 實作 — 新增 VocabSource model + VocabEntry 加 source**
```python
# api_models.py — VocabEntry 前面新增
class VocabSource(BaseModel):
    type: Literal["book", "web"]
    title: str | None = None
    url: str | None = None       # web only
    chapter: str | None = None   # book only

# VocabEntry class — 加在 root_form 之後
    source: VocabSource | None = None
```

- [ ] **Step 4: 實作 — Card SQLModel 加 source column**
```python
# cards.py Card class — 加在 is_archived 之後
    source: str | None = SQLField(default=None)  # JSON string: {type, title, url, chapter}
```

- [ ] **Step 5: 實作 — migration**
在 `_migrate_review_columns` 的 `review_columns` dict 中新增：
```python
    "source": "TEXT",
```

- [ ] **Step 6: 實作 — cards.add() 接受 source 參數**
`cards.py:123` `def add(...)` 新增參數 `source: str | None = None`，在建立 Card 時傳入。

- [ ] **Step 7: 實作 — vocab_service.py 傳遞 source**
`vocab_service.py:510-517` `cards.add(...)` 呼叫中新增：
```python
    source=json.dumps(entry.source) if entry.source else None,
```

- [ ] **Step 8: 實作 — CardResponse 加 source**
```python
# api_models.py CardResponse — 加在 notebookId 之後
    source: VocabSource | None = None
```

- [ ] **Step 9: 實作 — card_response() 回傳 source**
`vocab_service.py:116-139` CardResponse 建構中新增：
```python
    source=VocabSource(**json.loads(card.source)) if card.source else None,
```

- [ ] **Step 10: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_vocab_source.py -v`
Expected: PASS

- [ ] **Step 11: 跑既有 test 確認無 regression**
Run: `cd backend && python -m pytest tests/ -x -q`
Expected: all PASS

- [ ] **Step 12: Commit**
`api: add source field to VocabEntry and CardResponse`

---

## Task 2: Backend — CORS 支援 Chrome Extension

**Files:**
- Modify: `backend/src/kg/settings.py:40-45`
- Modify: `backend/src/kg/api.py:200-206`
- Test: `backend/tests/test_cors_extension.py`

- [ ] **Step 1: 寫 failing test**
```python
# backend/tests/test_cors_extension.py
"""Verify CORS allows chrome-extension origins."""
from kg.settings import load_settings
import os

def test_cors_includes_chrome_extension():
    os.environ["CORS_ORIGINS"] = "https://wordnexus.lol,chrome-extension://abcdef123"
    s = load_settings()
    assert any(o.startswith("chrome-extension://") for o in s.cors_origins)
    del os.environ["CORS_ORIGINS"]
```

- [ ] **Step 2: 跑 test 確認通過**（這個 test 其實已經可以 pass，因為 CORS_ORIGINS 是 env-driven）
Run: `cd backend && python -m pytest tests/test_cors_extension.py -v`

- [ ] **Step 3: 更新 settings.py 預設值**
```python
# settings.py:40-45 — 在預設 tuple 中加入開發用 origin
cors_origins: tuple[str, ...] = (
    "https://wordnexus.lol",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)
```
保持不變 — production 用 `CORS_ORIGINS` env var 加入 `chrome-extension://<id>`。

- [ ] **Step 4: 在 api.py CORS middleware 加 PATCH method**
```python
# api.py:200-206
allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
```
（side panel 未來可能需要 PATCH，而且現有 API 已有 PATCH endpoint）

- [ ] **Step 5: Commit**
`api: support chrome-extension CORS origin + add PATCH method`

---

## Task 3: Backend — Web OAuth Flow

**Files:**
- Create: `backend/src/kg/routers/web_auth.py`
- Create: `backend/src/kg/templates/login.html`
- Create: `backend/src/kg/templates/login_success.html`
- Modify: `backend/src/kg/api.py:301-310` (register router)
- Modify: `backend/src/kg/settings.py` (add google_client_id_web, chrome_extension_id)
- Test: `backend/tests/test_web_auth.py`

- [ ] **Step 1: 寫 failing test**
```python
# backend/tests/test_web_auth.py
"""Tests for web OAuth login flow endpoints."""
from fastapi.testclient import TestClient

def test_google_login_redirects(test_app):
    client = TestClient(test_app)
    resp = client.get("/auth/web/google/login", follow_redirects=False)
    assert resp.status_code == 307
    assert "accounts.google.com" in resp.headers["location"]

def test_login_page_renders(test_app):
    client = TestClient(test_app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Google" in resp.text
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_web_auth.py -v`
Expected: FAIL (endpoints don't exist)

- [ ] **Step 3: 實作 — settings 新增**
```python
# settings.py — 新增欄位
    google_client_secret: str = ""
    google_redirect_uri: str = "https://wordnexus.lol/auth/web/google/callback"
    chrome_extension_id: str = ""  # filled in production
```
`load_settings()` 中對應讀 env。

- [ ] **Step 4: 實作 — login.html 模板**
```html
<!-- backend/src/kg/templates/login.html -->
<!-- 簡潔登入頁：Google Sign-In 按鈕 + Apple Sign-In 按鈕 -->
<!-- 使用 KG design tokens（inline CSS variables） -->
```

- [ ] **Step 5: 實作 — login_success.html 模板**
```html
<!-- 登入成功頁面 -->
<!-- 嘗試 chrome.runtime.sendMessage 傳 token -->
<!-- Fallback: 顯示 token 複製按鈕 -->
<script>
  const token = "{{ token }}";
  const extId = "{{ extension_id }}";
  if (chrome?.runtime?.sendMessage) {
    chrome.runtime.sendMessage(extId, {type: "auth_token", token}, (resp) => {
      if (resp?.ok) document.getElementById("status").textContent = "已登入，可關閉此頁";
    });
  }
</script>
```

- [ ] **Step 6: 實作 — web_auth.py router**
```python
# backend/src/kg/routers/web_auth.py
router = APIRouter()

@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.get("/auth/web/google/login")
async def google_login(request: Request):
    # Build Google OAuth URL with redirect_uri
    # RedirectResponse to accounts.google.com/o/oauth2/v2/auth

@router.get("/auth/web/google/callback")
async def google_callback(code: str, request: Request):
    # Exchange code for id_token
    # Reuse existing verify_google_token + resolve_and_link_user
    # Create JWT
    # Return login_success.html with token

@router.post("/auth/web/apple/callback")
async def apple_callback(request: Request):
    # Apple posts form data to callback
    # Reuse existing verify_apple_token + resolve_and_link_user
    # Create JWT
    # Return login_success.html with token
```

- [ ] **Step 7: 實作 — api.py 註冊 router**
```python
# api.py — 在 auth_router 之後
app.include_router(web_auth_router)
```

- [ ] **Step 8: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_web_auth.py -v`
Expected: PASS

- [ ] **Step 9: 跑全部 test 確認無 regression**
Run: `cd backend && python -m pytest tests/ -x -q`
Expected: all PASS

- [ ] **Step 10: Commit**
`api: add web OAuth flow for Chrome extension login`

---

## Task 4: Chrome Extension — 專案結構 + Design Tokens

**Files:**
- Create: `chrome-extension/manifest.json`
- Create: `chrome-extension/shared/tokens.css`
- Create: `chrome-extension/shared/theme.js`
- Create: `chrome-extension/shared/api.js`
- Create: `chrome-extension/background.js`
- Create: `chrome-extension/fonts/` (字型檔)

- [ ] **Step 1: 建立 manifest.json**
```json
{
  "manifest_version": 3,
  "name": "KG 詞彙助手",
  "version": "0.1.0",
  "description": "閱讀時選詞翻譯，建立詞彙知識圖譜",
  "permissions": ["activeTab", "sidePanel", "storage"],
  "host_permissions": ["https://wordnexus.lol/*"],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [{
    "matches": ["<all_urls>"],
    "js": ["content/content.js"],
    "run_at": "document_idle"
  }],
  "side_panel": {
    "default_path": "sidepanel/index.html"
  },
  "options_ui": {
    "page": "options/options.html",
    "open_in_tab": true
  },
  "externally_connectable": {
    "matches": ["https://wordnexus.lol/*"]
  },
  "web_accessible_resources": [{
    "resources": ["fonts/*", "shared/tokens.css"],
    "matches": ["<all_urls>"]
  }],
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  },
  "key": ""
}
```

- [ ] **Step 2: 建立 tokens.css — 完整 design token mapping**
從 iOS AppTheme.Palette、AppMetrics、VocabSkin 1:1 映射：
- Light / Dark / Sepia 三套色彩 via `[data-theme]` selector
- Typography：font-family + size scale
- Spacing：micro~xxl
- Radii：sm~card~overlay~chip
- Motion：ease curves + durations
- `@font-face` 宣告 Athelas、ElmsSans、CormorantGaramond

- [ ] **Step 3: 建立 theme.js — 主題切換**
```javascript
// 讀 chrome.storage.local theme 設定
// 套用 data-theme attribute
// 監聽 storage.onChanged 即時切換
// export: initTheme(root), setTheme(name), getTheme()
```

- [ ] **Step 4: 建立 api.js — backend API client**
```javascript
// 從 chrome.storage.local 讀 auth_token
// fetch wrapper: 自動帶 Authorization header
// 方法: translate(word, context), translatePhrase(text, context),
//        explain(word, context), addVocab(entries), listVocab(since),
//        lookupWord(word)
// 錯誤處理: 401 → 清 token + 通知重新登入
const API_BASE = "https://wordnexus.lol";
```

- [ ] **Step 5: 建立 background.js — service worker**
```javascript
// 監聽 chrome.runtime.onMessage: 轉發 API 呼叫
// 監聽 chrome.runtime.onMessageExternal: 接收 OAuth token
// 管理 auth state
// Side panel 開關控制
```

- [ ] **Step 6: 放入字型檔**
複製 Athelas-Regular.woff2, Athelas-Bold.woff2, ElmsSans-Regular.woff2, ElmsSans-Bold.woff2, CormorantGaramond-Italic.woff2 到 `chrome-extension/fonts/`

- [ ] **Step 7: 手動載入 extension 驗證**
在 Chrome `chrome://extensions` 以 developer mode 載入 unpacked → 確認無報錯

- [ ] **Step 8: Commit**
`chrome: project scaffold with manifest, design tokens, api client`

---

## Task 5: Chrome Extension — Content Script + 選詞 Popup

**Files:**
- Create: `chrome-extension/content/content.js`
- Create: `chrome-extension/content/popup.js`
- Create: `chrome-extension/content/popup.css`

- [ ] **Step 1: 實作 content.js — 選取偵測**
```javascript
// 監聽 mouseup 事件
// window.getSelection() 取得選取文字
// 過濾：1-200 字元、非空白
// 擷取 context：選取範圍所在句子（用 Range.startContainer 找段落文字）
// 擷取 source：{ type: "web", title: document.title, url: location.href }
// 建立 Shadow DOM host element
// 注入 popup.css + popup.js
// 定位 popup 在選取文字附近
// 點擊外部或 Esc → 移除 popup
```

- [ ] **Step 2: 實作 popup.css — 浮動翻譯 UI**
```css
/* 使用 tokens.css 變數 */
/* 結構：card container → header (word + POS chip) → body (translation) → expand (explanation) → footer (action button) */
/* 狀態：loading → translated → saved → error */
/* 動畫：fade-in (--ease-quick)、content-swap (--transition-content-swap) */
/* 最大寬度 360px，圓角 --radius-overlay (13px) */
```

- [ ] **Step 3: 實作 popup.js — 翻譯 + 加詞邏輯**
```javascript
// 接收 { word, context, source } 參數
// 判斷 ≤50 字元 → chrome.runtime.sendMessage({type: "translate", ...})
//        >50 字元 → chrome.runtime.sendMessage({type: "translatePhrase", ...})
// 渲染翻譯結果：word, pronunciation, POS chip, translation
// 展開按鈕 → sendMessage({type: "explain", ...}) → 顯示解釋
// 「加入詞彙」按鈕 → sendMessage({type: "addVocab", entries: [{word, translation, context, source}]})
// 成功 → 按鈕變 success 狀態 "已加入"
// 未登入 → 顯示提示 + 開 options 連結
```

- [ ] **Step 4: 手動測試**
載入 extension → 開任意網頁 → 選取英文單字 → 確認 popup 浮出 → 翻譯顯示 → 加入詞彙

- [ ] **Step 5: Commit**
`chrome: content script with selection popup + translate + add vocab`

---

## Task 6: Chrome Extension — Side Panel

**Files:**
- Create: `chrome-extension/sidepanel/index.html`
- Create: `chrome-extension/sidepanel/app.js`
- Create: `chrome-extension/sidepanel/styles.css`

- [ ] **Step 1: 實作 index.html — 骨架**
```html
<!-- 引入 tokens.css + styles.css -->
<!-- 結構：header (title + theme toggle) → search bar → vocab list container → detail panel -->
<!-- 四種狀態容器：loading / empty / error / content -->
```

- [ ] **Step 2: 實作 styles.css — Side Panel 樣式**
```css
/* 基於 tokens.css */
/* VocabListCard 樣式：word (--text-row-word, --font-mono) + POS + translation + source icon */
/* AppSearchField 樣式：圓角 --radius-sm, padding --sp-sm */
/* Detail 展開區：翻譯、詞性、例句、context、來源 URL */
/* Empty state / Error state / Loading skeleton */
/* 寬度自適應 side panel（~400px） */
```

- [ ] **Step 3: 實作 app.js — 詞彙列表 + 搜尋 + 詳情**
```javascript
// 初始化：initTheme(), loadVocabList()
// loadVocabList(): chrome.runtime.sendMessage({type: "listVocab"})
//   → 渲染 VocabListCard 列表
//   → 四狀態切換：loading / empty / error / content
// 搜尋：input event → debounce 300ms → 前端過濾 word + meaning
// 點擊 card → toggle detail 展開
//   → 顯示：meaning, pos, examples, collocations, note, source (可點擊 URL)
// 主題切換按鈕：light → dark → sepia cycle
// 列表項顯示 source icon：🌐 (web) / 📖 (book/null)
```

- [ ] **Step 4: 手動測試**
點 extension icon → side panel 開啟 → 詞彙列表載入 → 搜尋過濾 → 點擊展開詳情 → 主題切換

- [ ] **Step 5: Commit**
`chrome: side panel with vocab list, search, detail view`

---

## Task 7: Chrome Extension — Options 頁 + 登入

**Files:**
- Create: `chrome-extension/options/options.html`
- Create: `chrome-extension/options/options.js`
- Create: `chrome-extension/options/options.css`

- [ ] **Step 1: 實作 options.html**
```html
<!-- KG design token 樣式 -->
<!-- 結構：帳號區（登入狀態 / 登入按鈕 / 登出按鈕）→ 主題選擇（三選一 radio）→ 版本資訊 -->
```

- [ ] **Step 2: 實作 options.js**
```javascript
// 載入時：讀 chrome.storage.local → 顯示登入狀態 + 當前主題
// 登入按鈕：chrome.tabs.create({url: "https://wordnexus.lol/login"})
// 登出按鈕：清除 chrome.storage.local auth_token + user_id
// 主題選擇：setTheme() + 寫入 storage
```

- [ ] **Step 3: 實作 options.css**
```css
/* 用 tokens.css 統一風格 */
/* SettingsRow 樣式：label + control, padding --card-padding */
/* 按鈕用 AppActionButton 樣式 */
```

- [ ] **Step 4: 手動測試**
Options 頁 → 點登入 → 跳 wordnexus.lol/login → OAuth → token 回傳 → 顯示已登入 → 主題切換生效

- [ ] **Step 5: Commit**
`chrome: options page with login flow and theme settings`

---

## Task 8: 整合測試 + 收尾

**Files:**
- Modify: `chrome-extension/manifest.json` (最終調整)
- Test: 全流程手動測試

- [ ] **Step 1: 跑 backend 全部 test**
Run: `cd backend && python -m pytest tests/ -x -q`
Expected: all PASS

- [ ] **Step 2: 全流程測試清單**
1. 安裝 extension → options 自動開啟
2. 登入 → OAuth → token 回傳 → 顯示已登入
3. 選詞（短，≤50 字元）→ popup → 翻譯 → 加詞 → 已加入
4. 選詞（長，>50 字元）→ popup → phrase 翻譯
5. 選詞 → 展開 → 解釋顯示
6. Side panel → 列表載入 → 搜尋 → 詳情展開
7. 新加的詞出現在 side panel（含 web source icon）
8. 主題切換（options 和 side panel 同步）
9. 登出 → 選詞 → 顯示未登入提示
10. iOS app 確認 source 欄位不影響既有功能（source=null）

- [ ] **Step 3: 修正發現的問題**

- [ ] **Step 4: Final commit**
`chrome: KG Chrome Extension v0.1.0`
