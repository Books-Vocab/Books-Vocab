<!-- doc-meta
tier: snapshot
authority: derived
update_trigger: manual
scope:
  - web/src/surfaces/reader-live/
  - web/src/App.tsx
verified_against: a0e90a86
-->
# Web Reader 引擎 Spike — 選型結論與原型能力邊界

> Dated snapshot（2026-06-11）。「99.9% 仿真 web 版」Reader 從靜態皮層走向功能的第一塊探索。
> 原型程式碼：`web/src/surfaces/reader-live/`（lazy，僅 `?surface=reader-live` 啟用，
> **不動既有 parity 路徑**）。讀前看 `verified_against`，可能已過時。

## TL;DR

- **選型：epub.js（`epubjs@0.3.93`）**。理由見下方評估表。readium ts-toolkit 與自刻皆棄。
- 原型已動：真 EPUB 載入、橫向分頁、章節跳轉、單字點選取詞+context+座標、CrimsonPro serif 套用。**全部當下驗證過**（playwright headless，383×852）。
- 最大風險：選詞層的 **iframe sandbox**（epub.js section iframe 無 `allow-scripts`）強制選詞邏輯必須跑在父 context；座標換算（父框 ↔ column-paginated iframe）是生產化最需硬化的一塊。

## 1. 技術選型評估

| 軸 | epub.js ✅ | readium ts-toolkit | 自刻（JSZip+CSS columns） |
|---|---|---|---|
| 成熟度 | 多年穩定、API 凍結、TS types 隨包 | `@readium/navigator@2.6.0` 2026-06 才發布，README 無 pagination/穩定性聲明，文檔稀薄 | N/A（從零） |
| 分頁模型 vs iOS Readium | `flow:'paginated'` = CSS columns，與 iOS Readium reflowable 同款橫向翻頁體感 | 同家族（理論最對齊），但 navigator 太新、整合風險高 | 需自己實作 column 切頁 + locator |
| 選詞/高亮 hook | section 渲染進 iframe，父框可拿 `contents.document` 直接綁監聽 | 需摸索其 decoration/selection API | 完全可控但全部自寫 |
| 與既有 parity CSS 注入相容 | `themes.registerCss()` 注入 @font-face + body 排版，與 parity reader token 同源 | 注入機制未驗證 | 自己掌控 |
| bundle 重量 | **78KB gzip**（epub.js+jszip，lazy chunk，不進 parity bundle） | 未量（多包） | 最小但工時最大 |
| 工時 | 最低（半天出可動原型） | 中高（API 探索） | 最高 |

**決策**：spike 階段「貪精不貪廣」+ 風險最小化 → epub.js。iOS 的選詞/取 context 本就是注入 webview 的**純 JS（非 Readium API）**，故與 web 渲染引擎解耦 —— 選 epub.js 不會綁死未來；若日後要極致對齊 Readium locator，可再評估 ts-toolkit，但非 spike 必要。

## 2. 原型能力清單（已驗證）

| 能力 | 狀態 | 驗證證據 |
|---|---|---|
| 載入真 EPUB | ✅ | Readium test book `childrens-literature.epub`（161KB，放 `web/public/spike/`）；title 解析 = "Children's Literature" |
| 橫向分頁（CSS columns） | ✅ | `flow:'paginated'`，iframe 渲染，截圖確認逐頁版面 |
| 翻頁（左右半屏熱區） | ✅ | 連點 next → progress 0% → 1% → 4%（locations 生成後）|
| 章節跳轉 | ✅ | TOC 面板列 nav 條目，點擊 `rendition.display(href)` 跳轉成功 |
| 單字點選 → word + context + 座標 | ✅ | 點 "Raymond" → wordTap log：word=Raymond, ctx="Alden, Raymond Macdonald, Why the Chimes Rang…"；浮層帶 `--x/--y` 座標 |
| CrimsonPro serif 套用（與 parity 同源） | ✅ | `themes.registerCss` 注入 @font-face（絕對 URL）+ body 排版；body prose 截圖確認 serif 渲染 |
| 進度模型（iOS totalProgression 對應） | ✅ | `book.locations.generate(1600)` 背景生成，`percentageFromCfi` 算百分比 |
| 隔離（不污染 parity） | ✅ | build 後 parity bundle hash 不變（`index-BotrPX5Y.js` 107.66KB gzip 恆定）；epub.js 獨立 lazy chunk |

**不在原型範圍（spike 刻意省略）**：翻譯/詞庫接線、已收藏詞 highlight 重畫、設定面板 live 綁定、dark theme、locator 持久化、PDF 路徑。

## 3. 與 iOS Readium 行為的已知差異

| 項目 | iOS Readium | web epub.js 原型 | 影響 |
|---|---|---|---|
| 選詞 JS 注入點 | 注入 WKWebView（同 webview，`window.webkit.messageHandlers` 回傳） | **section iframe 是 sandboxed（無 allow-scripts）→ 注入 `<script>` 被擋**；改從父 context 綁 `contents.document` 監聽 | 架構差異。生產化須沿用「父框綁監聽」路線，不可走注入 script |
| 座標回傳 | webview 內座標，native 直接用 | iframe 內 rect + frame `getBoundingClientRect()` 位移 → 父框座標。column-paginated iframe 的座標換算未完全硬化 | **最需硬化**：翻頁/resize/column 偏移下浮層定位要重測 |
| highlight 重畫 | `__markVocabWords` set-diff 權威重畫（BridgePlanner） | 未實作 | 生產化需移植 highlight 注入（epub.js `annotations` API 或自寫 span 包裹） |
| context 切句 | `Intl.Segmenter` locale-aware + fallback | 原型用簡化 300 字窗（未接 Segmenter） | 低；移植 iOS 既有 Segmenter 邏輯即可 |
| locator | Readium Locator（精確、可跨格式） | epub.js CFI + locations 百分比 | 生產化的進度持久化需定 contract（對齊 architecture.md library migration 的 `last_locator_json`）|
| 字體 | bundled @font-face WKWebView | @font-face 絕對 URL 注入 iframe（CORS 同源 OK） | 無，已驗證 |

## 4. 走向生產的工作量級估計

| 模塊 | 量級 | 說明 |
|---|---|---|
| 選詞座標硬化 | **M** | column-paginated iframe ↔ 父框座標換算，含翻頁/resize/RTL；spike 已證可行但未窮舉邊界 |
| 已收藏詞 highlight | M | 移植 iOS set-diff 重畫；epub.js annotations 或自寫 span 注入 |
| 翻譯/詞庫接線 | M | 接 backend `/api/vocab` + translate；UI 殼用既有 parity TranslationPanel |
| 設定 live 綁定 | S–M | 字級/行距/主題/字體 → `rendition.themes` 動態更新（hook 已備） |
| locator 持久化 contract | M | 對齊 architecture.md library backend migration（PR6），EPUB/PDF 共用 position contract |
| 章節 TOC 視覺接 parity TocPanel | S | 原型用簡化 TOC；接既有 `TocPanel.tsx` 視覺殼 |
| dark theme / 多本書 / 匯入 | M | spike 未碰 |
| **總計** | **約 2–3 週**（單人，不含翻譯後端既有） | reader 本體骨架 spike 已清掉最大未知 |

## 5. 入口與檔案

- 啟用：`http://localhost:5180/?surface=reader-live`（dev）。
- `web/src/surfaces/reader-live/ReaderLiveScreen.tsx` — 原型本體（dynamic import epub.js）。
- `web/src/surfaces/reader-live/reader-live.css` — 原型樣式（沿用 reader token 語彙，幾何原型級）。
- `web/src/App.tsx` — `?surface=reader-live` 走獨立 lazy 分支，**不經 `resolveHarnessConfig`**（parity 路徑零改動）。
- `web/public/spike/childrens-literature.epub` — 測試書（Readium swift-toolkit test fixture，public domain）。

## 6. 依賴變更

- 新增 `epubjs@0.3.93`（dependencies）。lazy chunk 78KB gzip，僅 spike 路徑載入。
- `npm audit`：epub.js 舊 transitive deps 報 2 high（非 spike 引入、不進主路徑）；生產化前評估升級或替換。
