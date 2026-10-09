<!-- doc-meta
tier: reference
authority: derived
update_trigger: release-change
scope:
  - ios/BooksAndVocab/
  - ops/release_changelog.sh
verified_against: 3d929f414bfb4b61aec283aea70f40db7acf739c
-->
# iOS changelog

最新在上，一版一節。每節：zh-Hant 使用者說明（商店在地化語言）＋ en 短版 → Changes（New／Improved／Fixed，只列使用者看得到的）→ Internal 一行 → Builds 表。zh-Hant／en 區塊同時是 App Store「What's New」來源，各 ≤ 4000 字元，貼進 ASC 前不得含條目編號或內部用語。

維護契約：每個合併進 main 的使用者可見變更，發版 agent 在發版前用 `./ops/release_changelog.sh ios --draft <since-ref>` 產生草稿（`<since-ref>` 必須明確帶：預設起點是最近的 released tag `ios/x.y.z`，而 `ios/2.0.1` 尚未物化〔2.0.1 尚未上架，ASC 2026-10-09 確認〕，預設會錨在 `ios/2.0.0` 而重複列出 2.0.1 的變更。起點取「最近一個實際上傳／送審的 build tag」，現為 `ios/2.0.1+13`（finalize 建立後；之前為 `ios/2.0.1+12`）；待 `./ops/release.sh shipped ios` 物化 `ios/2.0.1` 後，起點改用該 tag，或省略即可）、策展後貼進 `## Unreleased`。`./ops/release.sh release ios <ver>` 必須在**候選 commit 內**把 `## Unreleased` 改名為 `## <ver>` 並補日期與 Builds 表，再重開空的 `## Unreleased`（release.sh 由另一條 lane 擁有，目前尚未自動化這一步，由發版 agent 手動在同一候選 commit 完成）。不列：test／fixture／chore／ci／refactor／docs／ops、被 feature flag 關閉的功能（Release 的 podcast 為 off，見 `KGFeatureFlags.swift`）、同一週期內加了又撤回的功能（淨額為零）。

## Unreleased
（自 `ios/2.0.1+13`，截至 main `ca86dffa1`；尚無條目）

## 2.0.1 (build 13)
2026-10-09 同版重送（build 13）。2.0.1 從未上架：ASC 於 2026-10-09 僅有 2.0.0 為 READY_FOR_SALE、沒有 2.0.1 的 App Store 版本記錄，build 7–12 只上傳到 TestFlight。以下為 2.0.0 → build 13 的淨變更（已含 build 12 之後至 main `ca86dffa1` 的全部 iOS 變更）。

### 使用者說明（zh-Hant）
新增「探索」：瀏覽官方公開牌組並一鍵複製成自己的單字本（離線時會提示）。複習卡片重新設計：版面編輯器（正常／精簡）、閱讀設定與複習設定改為原生表單並附即時預覽，卡面不再透出下一張的字，每本單字本可有獨立複習設定。新增連結（Add Link）全面改版：手動建立單字連結更穩、取消時立即移除待處理項目。閱讀器字級與標註控制統一、可調範圍有界，並新增自適應玻璃主題。匯入 TXT 檔時，支援以舊式編碼儲存的繁體與簡體中文檔案。同步改為逐步進度、不再重傳整份複習紀錄，並修正跨帳號切換、刪除單字本、遠端改名與排序不穩等問題。全面採用 iOS 26 Liquid Glass，最低支援 iOS 26.0。設定可管理 Pro API 金鑰，單字詳情可封存單字，單字本設定在多裝置間同步。CSV 匯出更安全；登入失敗時會顯示離線原因；刪除書籍失敗時會明確提示並保留單字連結。更多介面字串補齊本地化。

### What's New (en)
Explore lets you browse official public decks and copy one into your own notebook. The review card is redesigned with a layout editor, live previews and per-notebook review settings, and sync now shows step-by-step progress. Add Link is rebuilt: manual links are more reliable and cancelling clears the pending item at once. Reader typography and highlight controls are unified and bounded, with a new adaptive glass theme. TXT import now reads Traditional and Simplified Chinese files saved in legacy encodings, and CSV export is safer. The whole app adopts iOS 26 Liquid Glass (iOS 26.0 minimum). Manage Pro API keys in Settings, archive words from Word Detail, and notebook settings sync across devices. Many sync, notebook and stats fixes land, along with missing localizations.

### Changes
#### New
- Explore（Release 於 2026-08-05 開啟）：公開牌組瀏覽與複製、離線提示
- 複習卡版面編輯器（正常／精簡），可由複習工具列與設定進入；閱讀設定一頁兩入口、重置、即時預覽
- 單字詳情封存／取消封存與底部卡片管理區；設定中的 Pro API 金鑰管理 (#1252)
- 單字本翻譯設定、複習模式、複習時鐘改為伺服器 last-write-wins 跨裝置同步
- 閱讀器行距刻度與放開才提交的滑桿
- 每本單字本獨立的複習設定 (#1578)；詞彙連結卡流程 (#1577)；自適應玻璃閱讀主題挑選器 (#1587)
- Add Link 整合（S1–S5）：警告可見且可重試、建立可重試、取消手動連結立即移除待處理佔位 (#2036, #2196)
- 閱讀器字級與標註控制統一，字級顯示精確到 0.125 級
- 複習牌組整合（#2025 #2045 #2046 #2047）
- TXT 匯入支援 GB18030／Big5，並清除 XML 不合法字元

#### Improved
- iOS 26 Liquid Glass：閱讀器頂欄、複習頂欄與底部工具列、共用元件 (#1253)；最低支援版本提高到 iOS 26.0
- 「同步中…」變成六列逐步狀態與進度條，同步時間不再被截斷；不再每次重傳整份複習歷史；設定頁分組重整
- 統計：預測範圍切換有動畫、數值不折行、空指標仍可見、錯誤狀態精簡；今日到期與預測排除新卡與複習排除卡；統計運算與搜尋鍵快取更快
- 閱讀器可由無效定位自動恢復、書架閱讀進度可由 VoiceOver 朗讀
- 啟動時 iCloud 查詢與 EPUB 遷移移出主執行緒；閱讀器字型預熱離開主執行緒 (#2107, #2052)
- 同步拉取分頁取盡後才合併／清理；失敗時發出錯誤步驟；iCloud 遷移連 PDF 一起搬
- 付費牆試用說明改依 StoreKit 資格判斷；方案比較欄位隨 Dynamic Type 變大；VoiceOver 可朗讀單字滑桿與播放進度條
- 登入驗證失敗顯示離線原因、使用者取消則靜默；刪除帳號與知識圖譜失敗原因已在地化；補齊 31 個缺漏字串，單複數與歡迎頁「自動連結」用詞一致
- 發音與介面提示音遵守 app 音訊工作階段策略 (#2110)

#### Fixed
- 複習卡：正面貼合內容、背面區塊分隔線與版面預算、例句只在未揭曉面挖空、卡面不再透出下一張字、卡片寬度量測以卡片身分為鍵
- 逛公開牌組不再把 token 過期的使用者登出；切換語言不再就地重設 TipKit；已呈現的 sheet 會跟著 app 外觀換色
- 單字本同步提示只在真有變化時出現，取消不再謊報網路錯誤；未同步卡改硬刪；錯誤橫幅生命週期
- 書籍匯入取消保護；schema 復原時保留既有資料；重複圖譜連結合併
- 同步：遠端單字改名、編輯內容、待刪單字本、部分設定同步回饋、帳號切換後的單字本篩選與複習設定、跨裝置時鐘設定皆能正確反映；本機資料清除會清掉 lastSyncDate；重複 card id 不再崩潰
- 單字本／單字：選擇器儲存失敗會提示而非靜默關閉；詳情編輯後會刷新；封存單字排序穩定；單字與單字本排序、日曆排序確定；純標點不再被當成單字擷取；Unicode EPUB 選字保留
- 書籍匯入：取消、失敗或被取代的匯入不再留下孤兒檔；刪除書籍時一併刪除 TXT／MD 原檔；取消檔案選擇器不再報錯
- 刪除書籍時若檔案移除失敗，會明確提示失敗並保留該書的單字連結，不再讓單字顯示為已脫離書籍 (#2216, `389a84434`)
- 圖譜：範圍限定在目前單字本、節點身分穩定、重新點擊會開啟詳情、力導向滑桿可歸零
- 付費：訂閱商品載入狀態與取消不再誤報失敗；載入中停用管理訂閱按鈕
- Explore：離線時正確顯示離線說明（先前 `KGError.offline` 與被包裝的 `URLError` 未被判為離線）(#2108)
- CSV 匯出防範公式注入；Markdown 底線強調依 CommonMark 規則；解釋重試只重跑解釋

### Internal
UI World／fixture／selector 證據鏈、Sentry 可觀測性、injection 與 i18n 嚴格 lint、catalog 工作台、同步引擎與 service 拆分、單元測試編譯修復與死碼清理等；podcast 相關修正因 Release flag 關閉不列。字典卡（Dictionary card）在 build 7–9 內出現、於 build 10 前撤回，淨額為零故不列。

### Builds
| build | tag | commit | date | state |
|---|---|---|---|---|
| 13 | `ios/2.0.1+13`（finalize 時建立） | candidate `5fd183c95`；merged-main source 於 finalize 由 tag 填入 | 2026-10-09 | same-version resubmit candidate；尚未上傳 |
| 12 | `ios/2.0.1+12` | `c4103d6ee` | 2026-08-25 | uploaded to TestFlight, never shipped（superseded by 13） |
| 11 | `ios/2.0.1+11` | `07d0fa51f` | 2026-08-24 | uploaded to TestFlight, never shipped |
| 10 | `ios/2.0.1+10` | `a3f3e17f5` | 2026-08-17 | uploaded to TestFlight, never shipped（字典卡已撤回） |
| 9 | `ios/2.0.1+9` | `b3c7c20d1` | 2026-08-16 | uploaded to TestFlight, never shipped（仍含字典卡） |
| 8 | — | — | — | 未記錄 tag；never shipped |
| 7 | `ios/2.0.1+7` | `66ee0930c` | 2026-08-10 | uploaded to TestFlight, never shipped（首個 2.0.1，含字典卡） |

## 2.0.0
2026-07-13 上架（build 6），重大版本。

### 使用者說明（zh-Hant）
2.0 帶來全新底層：設定透過 iCloud 同步、自動連結開關與更順暢的複習翻卡。

### What's New (en)
2.0 ships a new foundation: iCloud-synced settings, an Auto-Link switch, and smoother review card flipping.

### Changes
#### New
- 設定經 CloudKit 跨裝置同步；設定新增「自動連結」開關
#### Improved
- 複習翻卡：移除殘影視圖樹、三張卡連續堆疊、快照持久化離開主執行緒；書架狀態透明化
#### Fixed
- 登出清理與登入後同步的競態；冷啟動暫停時鐘解析

### Internal
UI World 資料集與 catalog 治理、行銷截圖場景；Explore（唯讀牌組瀏覽與複製）與 podcast 程式已在樹內但 Release 旗標關閉，未對使用者開放。

### Builds
| build | tag | commit | date | state |
|---|---|---|---|---|
| 6 | `ios/2.0.0+6`, `ios/2.0.0` | `c81bdf417` | 2026-07-13 | shipped（build 5 被取代後重新送審） |
| 5 | `ios/2.0.0+5` | `253630616` | 2026-07-08 | superseded by build 6 |
