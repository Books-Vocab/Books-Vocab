<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - chrome-extension/
verified_against: 8bbd1aa2
-->
# Chrome Extension Feature Boundary

Books & Vocab Chrome extension（`Books & Vocab`, Manifest V3）— 網頁閱讀選詞 → 翻譯 → 寫入用戶詞庫，與 iOS app 共用 backend (`wordnexus.lol`)。

## 檔案清冊

### Entry Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `manifest.json` | — | MV3 manifest：`activeTab` / `sidePanel` / `storage` / `alarms` 權限（`alarms` 供 enrich 輪詢喚醒被殺的 worker），`host_permissions` 限 `wordnexus.lol/*` |
| `background.js` | ~300 | Service worker：sidepanel 開關、訊息路由（經 `KGPure.routeMessage`）、token 注入。**addVocab outbox（對齊 iOS 本地暫存→sync）**：加詞不再 inline POST，改 optimistic enqueue 進 `chrome.storage.local` 的 `vocab_outbox`（經 `KGOutbox` 純狀態機，entry 保留 `notebookId`）+ 立即回 ack；背景 `flushOutbox` single-flight（`flushInFlight`/`flushRequested`，每 `await` 後 re-read 防 lost-update，`withOutboxLock` promise-chain mutex 串行化所有 read-modify-write）依 notebook 分批 `POST /api/vocab?notebook_id=...` 收斂 `cardIds`，`reconcileAddResponse(..., notebookId)` 只收斂該 batch，失敗 `markFailed` 並排 `kg-outbox-retry` alarm（1 分鐘）喚醒 MV3 worker 重送；sidepanel `retryOutbox` route 會立即呼叫同一個 `flushOutbox()`。**enrich 回填（step 3+4）**：flush 收斂後 fire `triggerEnrichPolling(notebookId)`（`POST /api/pipeline?notebook_id=...` + `chrome.alarms` 30s×上限3 輪詢讀 `X-Pipeline-Pending`，poll state 存 `enrich_poll_state {attempts,notebookIds}` 耐 worker 重啟，逐 notebook `GET /api/vocab?notebook_id=...`）→ bump dirty 讓 sidepanel 重抓顯示 enriched 卡。**startup drain**：worker spin-up 時 top-level `flushOutbox()` 重試殘留。**vocab_dirty bump**：mutating 成功後 fire-and-forget 寫 `VOCAB_DIRTY_KEY=${Date.now()}.${++tick}`（單調遞增防同毫秒漏觸發），sidepanel `storage.onChanged` 靜默重抓 |

### Content Script Layer（網頁注入）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `content/content.js` | 679 | 選詞偵測、popup 顯示、選取範圍管理；與 sidepanel 透過 `chrome.runtime.sendMessage` 溝通；href 渲染走 `shared/pure.js safeUrl()`；popup 注入 closed Shadow DOM 並設 `data-theme` 令 token 生效。經 manifest `web_accessible_resources` `fetch` `tokens.css`→`kg-components.css`→`popup.css`（concat 順序 load-bearing：vars → base primitives → layout）注入 shadow root。**全域開關**：mouseup handler 依 storage key `kg_enabled`（預設開，僅顯式 stored `false` 關閉）early-return，`chrome.storage.onChanged` live-sync 免重整。**Notebook scope**：翻譯完成後 `hydrateNotebookPicker()` 讀 background `listNotebooks`，在 popup 內顯示目標 notebook selector（對齊 iOS Reader notebook picker）；變更寫回 `active_notebook_id`（inline mirror `KGPure.ACTIVE_NOTEBOOK_KEY`，isolated world 無法 reach shared global），`addVocab` message 帶目前 `notebookId`；缺值回 canonical `default`。**popup head（sticky）**：`headHTML(word)` 渲染 word + 工具鈕（speak/close），loading 與 translated 兩態共用以跨 render state 持存；`data-action` 鈕由 `showPopup` 一次性 delegated listener 處理（非 per-render add/explain handler）。**TTS**：`speakWord()` 走頁面 `window.speechSynthesis`（Web Speech API，零後端），best-effort no-op、開講前 cancel in-flight；`removePopup` 關閉時亦 cancel 防音訊殘留。**挑自然 voice**：不再只設 `utterance.lang`（避免桌機被分配低品質 compact voice 如 Fred），改用 `pickPreferredVoice(voices,lang)` 評分挑最自然 voice（Google +100 / natural-neural-premium-enhanced +80 / exact-lang +40 / cloud +10，只在同 base 語言內挑、無同語言回 null 不用外語唸）；content.js（isolated world）inline 鏡像 `KGPure` 版邏輯，處理 `getVoices()` 異步（空則等一次 `voiceschanged`）。inline SVG glyph（speaker/xmark，鏡像 `shared/icons.js`，content script 在 isolated world 無法 reach KGIcons 故 inline）。長文 popup `max-height: min(70vh,520px)` + `overflow-y:auto` + `overscroll-behavior:contain`。**invalidated-context 防禦**：orphan content script（extension reload 後遺留分頁）失去 `chrome.runtime.id`，`extensionContextValid()` + `sendMessageSafe()` 守門 — loadStyles short-circuit 空字串、三 sendMessage site（translate/explain/addVocab）降級顯示「請重新整理頁面」而非 uncaught throw（`CONTEXT_INVALIDATED_MSG` 於 load 時 valid context 解析並快取，dead runtime 不再呼 getMessage）。UI 字串走 `t()=chrome.i18n.getMessage` |
| `content/popup.css` | — | popup layout 樣式（含目標 notebook selector；消費 `kg-components.css` primitives + BEM `.kg-popup__*` layout class，非自繪 card/btn） |

### Sidepanel Layer（主 UI）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `sidepanel/index.html` | — | sidepanel 入口；serif 標題（CormorantGaramond）、icon-based 空狀態容器（由 `vocabEmptyState` 動態填入）、brand-hero CTA |
| `sidepanel/app.js` | ~1080 | UI 主邏輯：翻譯結果展示、加入詞庫、登入態管理；href 渲染走 `shared/pure.js safeUrl()`；error 狀態依 `classifyError` action 分為 login（brand-hero CTA）與其他（accent outline）。**Notebook scope + management**：`loadNotebookScope()` 先經 background `listNotebooks` 讀 `/api/notebooks`，`active_notebook_id` 存 `chrome.storage.local`；stale active id 回落 `default`，header 下方 `<select>` scope control 切換後重載 `GET /api/vocab?notebook_id=...`。scope row 右側 icon-only actions：新增 / 重新命名 / 刪除（default notebook disabled）；共用 `#notebookSheet` 表單，包含封面 preview、12 色 Morandi swatches、6 種 pattern choices（dots/lines/grid/waves/circles/noise），submit 分別送 `createNotebook` / `updateNotebook` payload `{name,color,cover_pattern}`，刪除送 `deleteNotebook`，成功後切到新 notebook 或回 `default` 並重載。**word-detail push 面板**（`#stateDetail` fixed 覆蓋，list 保留於下以存 scroll/search/filter）：row click → `pushDetail`，文件流對標 iOS `CardDocumentView`（hero word+pos+tier+speaker → 例句 serif italic 目標詞 highlight（`markWordInExample`+`parseInlineMarks`）→ meaning/定義 → 搭配 → 變化形 → 知識連結（對比/相關 group，target cardId 命中 loaded corpus 可 `pushDetail` 導航、`popDetail`/Escape 返回）→ 複習進度 → metadata footer → 來源）；navigation stack `detailStack`，TTS `speakWord` 走 Web Speech API，top-bar share action 對齊 iOS `ShareLink`：先嘗試 Web Share，失敗/不可用 fallback `navigator.clipboard.writeText(KGPure.vocabPlainTextExport(top))`，成功短暫切換 copied icon；detail 純唯讀。**跨 context 靜默刷新**：`chrome.storage.onChanged` 監看 `KGPure.VOCAB_DIRTY_KEY` → `refreshVocabSilently()` 重抓目前 notebook 的 `/api/vocab` 並 `applyView()` 重繪，保留 search/filter/sort/scroll 與開啟中的 detail（auth 變動優先：logout 使 list 失效）。**單字本複習狀態用 `GET /api/vocab` 的 `CardResponse` 真實欄位**（`reviewCount`/`nextReviewAt`/`lastReviewedAt`/`reviewIntervalHours`，經 `enrichWithReviewData`）— 非 mock：filter chip 計數、review CTA `dueCount`、每列複習進度條/標籤皆由 `pure.js` 純函數對標 iOS `VocabularyReview`/`WordRowPresentation` 計算；未學習列對齊 iOS「首輪 Xh」純標籤無進度條；列表 row **不顯示**複習狀態字（對齊 iOS `KGVocabPresenter` `showsReviewState:false`，狀態僅見於 detail 面板）— 複習時序由右側進度條+`dueLabel` 表達，`dueInfo`（iOS `rowStatus` 語意，未複習/待複習/下次 X，後者 `Intl.RelativeTimeFormat` zh-Hant）仍經 `enrichWithReviewData` 計算，供 outbox sync pill 文案與未來 `showsReviewState:true` context 用；chip/CTA 計數用全 corpus（搜尋時不隨 keystroke 縮水，對齊 iOS）。**filter chip / sort pill 可互動**（非 idle 展示）：chips `<button>` 多選切換複習狀態（`aria-pressed`，空選=全部）、sort pill `<button>` 開 dropdown menu 切 4 排序，選態經 `applyView()`（統一 filter→sort→render）走 `pure.js filterVocab`/`sortVocab`；無匹配不再是單行提示，改由 `KGPure.vocabEmptyState` 對齊 iOS `KGVocabEmptyState` 分支（整本空 > 搜尋 > 篩選 > 預設；單一篩選給 sparkles/checkmark.seal/leaf 專屬 icon），且搜尋/篩選無結果仍留在 content state 保留 list chrome；dropdown outside-click/Escape 關閉、active 項打勾用 `KGIcon` check。**加詞 outbox optimistic 顯示**：`loadVocabList`/`refreshVocabSilently` 讀 `chrome.storage` 的 `vocab_outbox`，經 `KGOutbox.pendingOutboxItems` 取 unresolved 且不在 server list 的詞，再依 `activeNotebookId` 過濾；`decoratePendingItem`（經 `normalizeVocabItem` 給完整形狀 + i18n 標記「同步中/待重試」，**不**跑 `enrichWithReviewData`——pending 無複習欄位）後由 `applyView` 置頂 prepend；`createRow` 僅對 `syncState` 為真的 outbox row 渲染 trailing 同步 pill（pending/failed 染色，failed 另顯示「重試」按鈕送 `retryOutbox` 立即 flush，普通 row 因 showsReviewState:false 無 trailing）+ row dim + 跳過 detail click（pending 非真卡）；對齊 iOS SyncView 待同步可見性 |
| `sidepanel/styles.css` | — | sidepanel 樣式；editorial surface 對齊官網 + iOS 北極星（single warm surface、serif headings、divider、z0/z1 shadow）。Notebook sheet cover editor 有固定 100px preview、12 色 swatch grid、pattern samples（dots/lines/grid/waves/circles/noise）與無 layout shift 的 selected states。單字本列表 filter chip bar 對齊 iOS `AppFilterChipBar`（兩列：chips 一列、sort+CTA 靠右一列；空選即全部，無「全部」chip；消費 `kg-component-structures.css`，僅留 active-count 脈絡填色覆寫）；sort pill dropdown 用 `.kg-sort-menu`（`--elevation-z3` 浮層 + chevron + active-item check + button reset）；空態共用 `.kg-empty` / `.kg-empty--inline` icon-based component，搜尋/篩選無結果與整本空走同一視覺；搜尋框對齊 iOS `AppSearchField`（`.kg-search-field` 複合：leading 放大鏡 + bare input + 有文字才現的 clear icon，surface 值對齊 `.kg-input` 契約）；**加詞 outbox 狀態 modifier**（`.kg-vocab-row--pending-sync` dim + `.kg-vocab-row__trailing--syncing`/`--sync-failed` muted/accent 染色，`.kg-vocab-row__sync-retry` 用 accent outline pill button，surface 層狀態覆寫，非重定義 primitive） |

### Options Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `options/options.html` | — | 設定頁面，**iOS grouped-list 風格**：小灰 section header + leading icon（`account`/`preferences`/`about` glyph）+ 圓角卡群組。「帳號」卡（`#auth-status` 已登入 / `#pro-status` 藍 PRO 徽章 / `#logout-area` 登出置底）；「偏好」卡合併三列（選字翻譯 `.kg-toggle` switch｜**「翻譯語言」** `#sourceLangSelect`→`#targetLangSelect` `.kg-select`+`#langHint`｜主題色塊選擇器），列間 `.kg-pref-divider` inset 分隔。載入 `shared/icons.js`（header icon 注入）；`[data-i18n]`/`[data-i18n-attr]` 標註 + `shared/i18n.js` include |
| `options/options.js` | 390 | 設定持久化（`chrome.storage`）；`kg_enabled` master toggle（fail-open read、revert-on-save-failure、跨分頁 `onChanged` sync、focus-visible + aria-hidden painted track）。**翻譯語言**：`SOURCE_LANGS`/`TARGET_LANGS`（value=backend 驗證碼，鏡像 `kg/languages.py`；label=各語 endonym，locale-stable 非 i18n 字串）填 select，登入後 `loadTranslationConfig`（經 background `getUserConfig`）載入、`onLangChange` 經 `updateUserConfig` PUT 持久化（server-canonical 回填、失敗 revert 至 `currentTranslation`）；登出禁用 + login hint；顯示狀態先經 `KGPure.optionsTranslationPresentation` 整理再套 DOM，對齊 iOS SettingsPresenter 的狀態分層。**Pro 狀態**：`loadProStatus`（經 background `getEntitlements`）依 `KGPure.optionsProPresentation` 渲染 `PRO` 徽章+`plan_name` 或免費標籤，無法判定（offline/401）時隱藏。`bgRequest` 統一 background 訊息錯誤封套（`{code,status}`）。UI 字串走 `t()=chrome.i18n.getMessage` |
| `options/options.css` | — | 設定頁樣式；editorial surface 對齊官網 |

### Shared Layer

| 檔案 | 行數 | 說明 |
|------|------|------|
| `shared/api.js` | ~270 | `wordnexus.lol` HTTP client + auth header；含 notebook CRUD：`listNotebooks`（`GET /api/notebooks`）/ `createNotebook` / `updateNotebook` / `deleteNotebook`；`addVocab(entries, notebookId)` 與 `listVocab(since,onResponse,notebookId)` 會帶 `notebook_id` query；含 `getUserConfig`（`GET /api/user/config`）/ `updateUserConfig(config)`（`PUT /api/user/config`，body = config patch 本身：`{translation:{source_lang,target_lang}}`（bad pair 422）或 `{vocab_ui:{active_notebook_id,updated_at}}` active notebook 游標；後端只 merge 有送的 group）/ `getEntitlements`（`GET /api/user/entitlements`，回 `{pro:{is_active,plan_name,…}}`）/ `triggerPipeline`（`POST /api/pipeline?notebook_id`，加詞收斂後觸發 server enrich）。`apiFetch` 支援 `onResponse` advisory hook（解構出避免漏進 fetch init，res.ok 後呼叫）讓 caller 偷讀 response header（如 enrich 輪詢的 `X-Pipeline-Pending`，經 MV3 worker `host_permissions` 特權跨域讀取，免 CORS `expose_headers`） |
| `shared/vocab-outbox.js` | ~210 | **加詞 outbox 純狀態機**（`globalThis.KGOutbox`，triple-export 同 `pure.js`）：`pending/synced/failed` 三態（鏡像 iOS `syncStatus`），entry 保留 `notebookId`（缺值 canonical `default`）；`enqueueAdd`（dedup unresolved 同 notebook+word，允許同 word 跨 notebook）/ `groupEntriesByNotebook`（flush batch 依 notebook 分組）/ `reconcileAddResponse(queue,cardIds,notebookId)`（server echo cardId byte-exact 且 notebook-scoped 收斂、SYNCED 終態、PENDING\|FAILED 皆解，**禁** content 比對，對齊 `sync_lifecycle.md:47-52` 不變式）/ `markFailed`（重試計數）/ `entriesToFlush`（pending∪failed）/ `pruneSynced` / `summarizeOutbox` / `pendingOutboxItems`（unresolved 且不在 server list 的條目→sidepanel optimistic row，byte-exact server 比對，攜帶 `notebookId`）/ `OUTBOX_KEY`。純函數，IO + flush 副作用在 `background.js` |
| `shared/vocab-outbox.test.js` | — | `vocab-outbox.js` 單元測試（`node --test`，20 case：byte-exact 收斂契約 / proto-key 防護 / 不可變 / dedup / failed 重送收斂 / cap / pendingOutboxItems 投影） |
| `background.test.mjs` | — | `background.js` effect harness（Node ESM + mocked `chrome.storage`/`chrome.alarms`/`fetch`）：驗證 addVocab route 進 `vocab_outbox` 後失敗會 `markFailed` + 排 `kg-outbox-retry`，手動 `retryOutbox` 可立即 flush 成功，以及 enrich polling 會對每個 triggered notebook 發 scoped `GET /api/vocab?notebook_id=...` |
| `shared/pure.js` | ~820 | 無副作用 helpers（字串處理、選詞 boundary、token 解析、`safeUrl()` URL scheme allowlist、`pickPreferredVoice(voices,lang)` TTS voice 評分挑選）；`normalizeVocabItem` 另保留 `linksByKind`/`inflections`/`cardId`（detail 面板知識連結與變化形所需，guard：linksByKind 須 plain object、inflections 須 array）；`normalizeNotebookList`/`normalizeNotebookItem` canonicalize `/api/notebooks` camel/snake aliases；`NOTEBOOK_PALETTE` / `NOTEBOOK_COVER_PATTERNS` mirror iOS `NotebookPalette` + backend whitelist；`validateNotebookName` / `normalizeNotebookColor` / `normalizeNotebookCoverPattern` / `buildNotebookCreatePayload` / `buildNotebookUpdatePayload` / `canDeleteNotebook` 集中 notebook management validation（name 1..100、hex color、cover pattern、default 不可刪；update 清 pattern 送 `cover_pattern:""`）；`pendingItemsForNotebook` 集中 sidepanel optimistic outbox row 的 active-notebook filter。**example 高亮純函數對標 iOS**：`markWordInExample`（port `VocabularyEntry.markWordInContext`：verbatim case-insensitive 首匹配 + stem fallback，輸出帶 `**…**` 標記的純文字、`word` regex-escaped 非 pattern）、`parseInlineMarks`（port `CardMarkdownInlineParser` 的 `**`/`==` mark → typed segments，空 span 丟棄、未閉合留字面）；**跨 context 刷新契約**：`VOCAB_DIRTY_KEY`（`'vocab_dirty'`，producer background.js / consumer app.js 共用避免 drift）+ `ACTIVE_NOTEBOOK_KEY`（`'active_notebook_id'`）+ `ACTIVE_NOTEBOOK_UPDATED_KEY`（`'active_notebook_updated_at'`，LWW 時戳）+ `resolveActiveNotebook`（兩層 LWW 對齊 iOS `ActiveNotebookLWW`）+ `buildVocabUiConfigPatch`（後端 `vocab_ui` snake_case wire），sidepanel/content 共用；active notebook 已**後端化**（chrome.storage.local 本地 + backend `vocab_ui` 橋樑：`loadNotebookScope` cold-start 經 `getUserConfig` LWW resolve、切換/submit/delete 經 `updateUserConfig` best-effort push，使 iOS/web 跨平台收斂）+ `isVocabMutatingKind`（`VOCAB_MUTATING_KINDS` 現僅 `addVocab`；唯讀 kind 回 false）；`routeMessage`/`ROUTABLE_MESSAGE_TYPES` 含 notebook CRUD + `retryOutbox` + `getUserConfig`/`updateUserConfig`/`getEntitlements`。複習狀態純函數對標 iOS SoT：`classifyReviewState`（`VocabularyReview.reviewState(at:)`：`reviewCount==0`→未學習，否則 `nextReviewAt<=now` 待複習/已複習）、`countReviewStates`（chip/CTA tally）、`compactReviewLabel`（iOS `CompactTimeFormatting` 閾值 byte-faithful port）、`reviewProgress`（`WordRowPresentation` ratio，start 由 `lastReviewedAt`??`nextReviewAt−intervalHours` schedule 推導）；單字本 view 管線純函數對標 iOS `VocabularyEntryPresentation` / `KGVocabEmptyState` / `CardDocument.plainTextExport`：`filterVocab`（mergedBucket 多選態 + search 謂詞合成 word/meaning contains）、`sortVocab`（4 排序：複習優先 due\<unlearned\<reviewed→`nextReviewAt` asc→tierPriority→word / 字母序 / 最近新增 / 難度；stable、不變更輸入）、`vocabEmptyState`（整本空 > 搜尋 > 篩選 > 預設；單一 filter icon 分支對齊 iOS）、`vocabPlainTextExport`（word/pos → first example → meaning/explanation paragraphs → collocations → source，空行分隔，供 detail share/clipboard）；Options 設定頁 presentation helpers：`optionsTranslationPresentation`（登入/錯誤/translation fallback → select disabled + hint key）與 `optionsProPresentation`（entitlement → PRO/free/hidden row state）；`normalizeVocabItem` 保留 `CardResponse` 複習欄位 + `difficultyTier`（難度排序）+ `updatedAt`（「最近新增」proxy，`CardResponse` 無 `dateAdded`） |
| `shared/pure.test.js` | — | `pure.js` 單元測試（含 `pickPreferredVoice` 6 個 TDD case） |
| `shared/css.test.js` | 55 | **CSS 不變式守門**：鎖死三份 `kg-components.css`（dist / shared / backend static）皆含全域 `[hidden]{display:none !important}` base reset，防 author 規則（如 `.kg-detail-panel{display:flex}`）壓過 UA `[hidden]` 致帶 hidden 屬性的 opaque panel 永久顯示、凍結 sidepanel |
| `shared/icons.js` / `shared/icons.test.js` | — | `shared/icons.js` 提供 header/detail/settings/notebook action glyph（含 plus/pencil/trash）；`shared/icons.test.js` 鎖 icon registry、currentColor SVG contract，以及 content.js isolated-world inline speaker/xmark glyph drift |
| `shared/theme.js` | 44 | 深淺色主題切換 |
| `shared/i18n.js` | 45 | static-DOM localizer（sidepanel/options）：依 `[data-i18n]` 換 `textContent`、`[data-i18n-attr="attr:key;…"]` 換屬性,值經 `chrome.i18n.getMessage`；key 缺失時保留原中文 fallback |
| `shared/tokens.css` | — | 設計 token（**生成檔**，由 `ops/gen_web_tokens.py` 從 `design-system/tokens.json` 產出，禁手改；`:root, :host` selector 供 closed Shadow DOM 生效） |
| `shared/kg-components.css` | — | component primitives（`.kg-card` / `.kg-btn` / `.kg-chip`，鏡像 iOS `AppCard`/`AppButton`/`AppTag`）。**生成檔**，由 `ops/gen_web_tokens.py` 從 `design-system/dist/kg-components.css` 複製（手寫源在 dist，禁手改此 copy；已納入 `--check` gate）。三 surface 共用一套 primitive 詞彙 |
| `shared/kg-component-structures.css` | — | 跨平台**複合元件結構**（primitive 之上的 BEM 結構契約，如 `VocabFilterChipBar` chips 容器 + `.class--active` modifier）。**生成檔**，由 `ops/gen_web_components.py` 從 `design-system/components.json`（結構 SoT）產出；token 以 `var(--*)` 引用，禁手改。sidepanel filter chip bar 消費此檔，僅在 surface CSS 留 active-count 脈絡填色覆寫 |
| `shared/fonts.css` | — | surface-local `@font-face`（woff2 URL）；包含 ElmsSans 400/700 + CormorantGaramond 500/600/700 upright + 400–600 italic。font *family* 為 tokens.css 的 `--font-*` token，URL 各 surface 自帶 |

### Assets

| 目錄 | 說明 |
|------|------|
| `fonts/` | woff2：ElmsSans-Regular/Bold、CormorantGaramond-Medium/SemiBold/Bold/Italic |
| `icons/` | 16/48/128 PNG |
| `_locales/zh_TW/messages.json` | chrome.i18n 訊息 SoT（含 content popup 目標 notebook selector、notebook scope/management/appearance sheet、`首輪 $time$` / `下次 $time$` / `$count$ 個連結` placeholder 替換、加詞 outbox 的 `同步中…`/`待重試`/`重試`）；manifest `name`/`description` 走 `__MSG_*__`，`default_locale: "zh_TW"` |

## 設計系統消費

三 surface（sidepanel / popup / options）消費同一套設計系統：

1. **Token 層** (`tokens.css`)：顏色、字體、間距、圓角、elevation、motion — 由 `ops/gen_web_tokens.py` 從 `design-system/tokens.json` 生成
2. **Primitive 層** (`kg-components.css`)：`.kg-btn`、`.kg-card`、`.kg-chip`、`.kg-input`、`.kg-link` — 鏡像 iOS 元件
3. **Surface 層** (`styles.css` / `popup.css` / `options.css`)：僅定義 BEM layout class，**不重寫 primitive 視覺屬性**

北極星五條落地：
- 單色頁面：toolbar + content 共用 `page-bg`
- Border 退場：list cards 無 border，分區走 divider + 留白
- Shadow 收斂：resting cards z0/z1，overlay z2+
- 單一強調色：`brand-hero` 奶黃 CTA、`accent` Morandi grey-blue 被動裝飾
- Motion 收斂：按鈕 tap-feedback triplet，非按鈕只動 bg/opacity

## 對外契約

- **Backend endpoints**：見 [`docs/reference/tech_index.md`](../tech_index.md) 對應 router 章節（含 `user.py` 的 `/api/user/config` 翻譯語言 GET/PUT、`/api/user/entitlements` Pro 訂閱態，由 options 頁消費）。Chrome 不維護自己的 endpoint 表。
- **Auth**：與 iOS 共享 Google / Apple 登入 backend；token 存 `chrome.storage.local`。Web OAuth 走 `/auth/web/apple/login`（GET redirect 至 Apple authorize endpoint）與 `/auth/web/google/login`。
- **Domain 白名單**：`host_permissions` 只放 `wordnexus.lol/*`，新 backend domain 變動需同步 `manifest.json`。
- **URL scheme allowlist（XSS defense-in-depth）**：sidepanel / content 渲染外部 href 一律走 `shared/pure.js safeUrl()`；僅放行 `http:` / `https:` / `chrome-extension:`，其餘（`javascript:` / `data:` / `vbscript:` / `file:` / `blob:` 等）一律 fallback `#`。

## 在地化（i18n）

- **機制**：`chrome.i18n` + `_locales/<locale>/messages.json`（訊息 SoT，現 zh_TW 89 keys）。manifest `default_locale: "zh_TW"`，`name`/`description` 用 `__MSG_*__`。
- **靜態 HTML**：`index.html` / `options.html` 元素加 `[data-i18n]`（換 textContent）/ `[data-i18n-attr]`（換屬性），include `shared/i18n.js` 於 DOM ready 套用；缺 key 保留原中文 fallback。
- **JS 動態字串**：content.js / app.js / options.js 用 `t()=chrome.i18n.getMessage`。例外：content.js 的 `CONTEXT_INVALIDATED_MSG` 於 load 時（context 仍 valid）解析並快取，避免 dead runtime 呼 getMessage。
- **新增語言**：只需加 `_locales/<locale>/messages.json`，無需改 code。

## 不在 scope 內

- iOS 端 SwiftData、SwiftUI、podcast、reader 模組 → 走 [`vocabulary.md`](vocabulary.md) / [`reader.md`](reader.md) / 等。
- Backend FastAPI router 實作 → [`tech_index.md`](../tech_index.md)。

## 變動時要做的事

| 動作 | 同 PR 同步 |
|------|-----------|
| 改 manifest 權限或 host 白名單 | 本檔「Entry Layer」段 + [`docs/reference/product_surface.md`](../product_surface.md) 對應 bullet |
| 新增 / 刪除主要 JS 檔案 | 本檔對應 Layer 表 |
| 新增 user-facing 字串 / 改 UI 文案 | `_locales/zh_TW/messages.json`（i18n SoT），JS 走 `chrome.i18n.getMessage`、靜態 HTML 走 `[data-i18n]` |
| 新增 chrome.storage 設定 key | 本檔對應 Layer 段 + [`docs/reference/product_surface.md`](../product_surface.md) bullet |
| 改 `shared/api.js` 呼叫的 backend endpoint | [`tech_index.md`](../tech_index.md) router 章節 |
| 改認證流程 | [`docs/sop/architecture.md`](../../sop/architecture.md) auth 段 |
| 改設計 token / 配色 | 改 `design-system/tokens.json` 再跑 `ops/gen_web_tokens.py` 重生 `shared/{tokens,kg-components}.css`（禁直接手改生成檔；drift 由 `ops/token_drift_check.py` 守） |
| 改複合元件結構（filter chip bar / 跨平台共用結構） | 改 `design-system/components.json`（結構 SoT）再跑 `ops/gen_web_components.py` 重生 `shared/kg-component-structures.css`（禁手改生成檔）；surface CSS 僅留生成器涵蓋不到的脈絡覆寫 |
| 改 surface 視覺（card / button / chip 外觀） | 三 surface（sidepanel / popup / options）現消費 `shared/kg-components.css` 的 `.kg-card`/`.kg-btn`/`.kg-chip` primitives；改視覺走 `tokens.json` → generator 重生，**勿在 surface CSS 手寫等價樣式**。各 surface 自有 CSS 僅放 BEM layout class（`.kg-list-card` / `.kg-popup__btn` / `.kg-group-card`）與 primitive 組合；重定義 base class 視為 bug |
| **改任何 chrome-extension 檔案後** | 跑 `ops/chrome_verify.sh`（三層：static / `node --test` / 真渲染 CDP smoke，零安裝）。它真載入並渲染 extension，能揪出 manifest/asset/syntax 破壞與 CSS cascade 致 `[hidden]` 元素仍可見這類 commit 前無法自動暴露的 bug；非互動 flow / 音訊 QA 仍須人工。無瀏覽器 host 用 `--static-only` |
| **對標 iOS 視覺** | 跑 `ops/chrome_parity.sh --audit`。contact sheet 只當全局概覽：`tools/shots.mjs` headless 截 10 個 UI case（sidepanel content light/dark/sepia · content popup notebook selector · outbox failed row · notebook sheet · detail · options · empty · error）。sidepanel/options case 注入 in-page mock 走 app.js 真實 render path；content popup case 用 `tools/content-popup-harness.html` 載入 production `content/content.js`，mock runtime/storage 後以 DOM selection 觸發真 Shadow DOM popup，並 assert selector 初始值與改選後 `addVocab.notebookId` 會跟著變。`tools/compare.mjs` 按共用 `tools/parity-manifest.mjs` 與 **Catalog snapshot**（`tools/ios-ref.mjs` 解析最新 usable `build/snapshots/catalog-full-<UTC>`，`KG_CATALOG_ROOT` override；無 root 先跑 `./ops/ios_ops.sh catalog snapshots`）並排成總覽圖——iOS 參考圖按 `{surface, scenario, appearance}` 定址、源頭可再生，dark case 對真 dark snapshot。細節檢查以 `tools/parity-audit.mjs` 產物為準：逐張 `diff.png` 看像素差異、`zoom.png` 放大比對 row/header/card 區塊、`palette.txt` 比較平均色與 dominant colors、`metrics.json`/`summary.json` 追 RMSE/MAE/SSIM/pHash drift。10 case 中 7 個有 iOS ref（content/dark/sepia/empty→Vocabulary List View、detail→Word Detail Presenter、notebook sheet→Notebook Edit、options→Settings）；content popup/outbox failed/error 為 Chrome 特有。resolver 回歸 `ops/tests/test_chrome_parity_refs.sh`（`test_ops.sh chrome-parity-refs`）。產物 git-ignored |
| 改 `kg-components.css` base/reset | **`[hidden]{display:none !important}` 全域 reset 為不變式**（author-important 壓過任何 author-normal 如 `.kg-detail-panel{display:flex}`，使帶 hidden 屬性的 opaque panel 真正隱藏）。手寫源在 `design-system/dist/kg-components.css`，經 `ops/gen_web_tokens.py` 傳播到 shared + backend/static + web/src/styles 三份副本；`shared/css.test.js` 鎖死三份皆含此 reset，移除即紅 |
