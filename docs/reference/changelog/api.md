<!-- doc-meta
tier: reference
authority: derived
update_trigger: release-change
scope:
  - backend/src/kg/api.py
  - backend/src/kg/routers/
  - ops/release_changelog.sh
verified_against: 3d929f414bfb4b61aec283aea70f40db7acf739c
-->
# API changelog

最新在上，一版一節；版號即 `backend/src/kg/api.py` 的 FastAPI `version`，對應 tag `api/x.y.z`。每節：zh-Hant 與 en 的 API 使用者（iOS app、Pro 外部整合）可感知摘要 → Changes（New／Improved／Fixed，只列 client 看得到的行為）→ Internal 一行。

維護契約：每個合併進 main 的 client 可見後端變更，發版 agent 用 `./ops/release_changelog.sh api --draft origin/prod` 產生草稿（api 一律明確帶 `origin/prod`：預設起點是最近的 `api/x.y.z` tag，而 `api/2.0.4` 缺漏，預設會錨在 `api/2.0.3` 而重複列出 2.0.4 已出貨的變更）、策展後貼進 `## Unreleased`。`./ops/release.sh release backend <ver>` 必須在**候選 commit 內**把 `## Unreleased` 改名為 `## <ver>`、補日期，再重開空的 `## Unreleased`（release.sh 由另一條 lane 擁有，目前尚未自動化這一步，由發版 agent 手動在同一候選 commit 完成）。不列：test／ci／refactor／docs／ops／純格式化，以及同一週期內加了又撤回的功能。「Unreleased」的定義是 `origin/prod..origin/main`（prod 即線上版本）。

## Unreleased
（`origin/prod` `91dc4d4ea` 之後，截至 main `3d929f414`，2026-10-09）

### 摘要（zh-Hant）
超出範圍或非有限數值的輸入現在回 400／422，而非 500；新增靜態頁 HEAD、robots.txt、sitemap.xml 與 favicon。共享牌組複製的卡片會被增量同步拉到，封存／刪除單字會讓相連單字同步更新。帳號刪除會清除全域日誌與訂閱索引。寬限期（billing grace period）訂閱的權限改以 Apple 提供的寬限到期時間為界，不再無限期保留。App Store 交易現在綁定到購買者的帳號，不能被其他帳號認領；存取記錄中的 token／code／state 參數會被遮蔽。

### Summary (en)
Out-of-range and non-finite inputs now return 400/422 instead of 500; static pages answer HEAD and robots.txt, sitemap.xml and favicon.ico are served. Copied shared-deck cards reach incremental pulls, archiving or deleting a word refreshes its linked peers, and account deletion also purges global log stores and the subscription index. Billing-grace-period entitlement is now bounded by Apple's grace expiry instead of lasting indefinitely. App Store transactions are now bound to the purchasing account and cannot be claimed by another one, and token/code/state values are redacted from access logs.

### Changes
#### New
- `robots.txt`、`sitemap.xml`、`favicon.ico`；靜態頁支援 HEAD
#### Improved
- 卡片回應帶出 reader／review 偏好；翻譯結果快取前先驗證型別；LLM 供應商路由於啟動時驗證
- 手動連結先經 judge 再解除封鎖，刪除已棄用連結會被拒絕；連結變更的 reconcile 只掃被改的一對
- 計費：embedding 與 chat prompt-cache 價格校正；已驗證的同步／對帳可通過通知水位
- 全域單字列表消除 N+1 查詢（#2402，`5bdc6b957`）
- review-event 增量拉取改走索引（`ingested_at` 一次性遷移為標準 UTC 格式），順序不變 (#2387)
#### Fixed
- 輸入：審查事件時間戳超出範圍回 400；非有限驗證輸入回 422；review counter 上限 int32、notebook sort_order 超界回 422；`DeckCopyRequest.notebookName` ≤ 100 字；單字 root_form 與 source 欄位有長度上限
- 同步：共享牌組複製的卡片在揭示時重新戳記；封存／取消封存／刪除單字會觸碰相連卡片的 `updated_at`；ops 連結操作與卡片搬移同理；筆記本於請求中途被刪除時卡片改寫入墓碑
- 計費：寬限期（`grace_period`）權限以 `grace_period_expires_at`（Apple 的 `gracePeriodExpiresDate`）為界；舊資料無此欄位時退回 `expires_at` + 16 天，兩者皆無則視為無權限（先前寬限期內的訂閱永遠視為有效）(#2411，修復 commit `699171fca`)
- 單字：混合大小寫字詞不再被 `_clean_content` 破壞；與靜態 PATCH 路徑同名的單字內容編輯可轉發；客戶端 highlight 保留、範例單字依邊界比對
- 帳號：連結帳號的 email 變更時保留 canonical；自刪帳號會清訂閱索引，且只解析仍存在的擁有者；清除全域日誌；管理員授權的 `expires_at` 須為合法值，避免髒資料變成永久 Pro
- Podcast：`series_id` 上限 64 字元；找不到音訊格式的請求回 404，不再預設為 m4a；音訊格式快取有上限 (#2396)
- 安全：`/sync` 與 `/reconcile` 以 `appAccountToken` 把 Apple 交易綁定到帳號，屬於其他帳號的交易回 403，已連結至不同帳號且無法證明身分者回 409（`resolve_claim_owner`）(#2476)；token／code／state 查詢參數在存取記錄與 admin 記錄環形緩衝中遮蔽（`mem_log.py`）(#2489)
- 安全／可觀測：網站回應現在確實帶 HSTS（TLS 終止於 Cloudflare，原本以 request scheme 判斷而恆不送，改依設定的公開 https 網址）(#2399)；`X-KG-API-Key` 自 Sentry 事件清除；`X-Request-ID` 淨化；5xx 錯誤保留上游狀態

### 部署注意（operator）
`JWT_SECRET` 下限由 16 提高到 **32 字元**，且拒絕 `changeme`、`secret`、`your-secret-key-change-in-production` 等占位值；production 設定較短或占位的密鑰時，服務**啟動即失敗**。部署前確認 `JWT_SECRET` 長度（可用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 產生）；既有登入 token 依舊密鑰簽發，更換密鑰會使其失效 (#2506)。

### Internal
embedding store 檔案鎖與 SQLite 路徑統一走鎖定的 data root、pytest 每程序獨立 KG_DATA_DIR、pipeline 錯誤隔離、死碼移除與 ruff 格式化。

## 2.0.4
2026-10-07，線上版本 `origin/prod` `91dc4d4ea`（`api/2.0.4` tag 缺漏，待補）。以下為 2.0.3 → 2.0.4 的淨變更。

### 摘要（zh-Hant）
新增 Pro 外部卡片 API（`/api/v1`，`X-KG-API-Key`）、每本單字本獨立的複習設定與單字連結卡流程。字典卡撤回，官方牌組複製回到一般卡片。大量輸入驗證收緊：空白、非有限數值、布林計數、反向範圍、空 cursor 一律明確回 4xx；所有時間比較改以 UTC 時刻為準，同步分頁排序確定。

### Summary (en)
Adds the Pro external card API (`/api/v1`, `X-KG-API-Key`), per-notebook review settings and the vocabulary link card flow. The dictionary card is retired and official deck copies are ordinary cards again. Input validation is tightened (blank values, non-finite numbers, boolean counters, reversed ranges and empty cursors return explicit 4xx), all timestamp comparisons use UTC instants, and sync paging order is deterministic.

### Changes
#### New
- Pro 外部卡片 API：`POST /api/v1/api-keys` 建 key，之後以 `X-KG-API-Key` 呼叫 card／enrich（契約見 `docs/reference/external_api.md`）
- 每本單字本持久化複習設定；詞彙連結卡流程；`PATCH /api/vocab/{word}/preferences` 接受 card mode，卡片偏好端點接線；含 `/` 的單字可走所有卡片路由
#### Improved
- 同步與分頁：增量同步、library、shared-decks、review-event 皆依 UTC 時刻比較與確定排序；cursor 綁定請求範圍與牌組版本；完整同步保留墓碑與圖譜連結
- library 拒絕不支援的資產格式 (#1187)，位置更新單調；podcast 範圍請求錯誤語意與分頁收緊
- 翻譯與額度回報扣用後的快照；health check 於資料庫失敗時降級
#### Fixed
- 驗證：空白單字／翻譯／筆記本名稱、空 cursor 與 since、非有限或布林的 review／podcast 數值、反向筆記本複習區間、自連結皆回明確錯誤而非 500 或靜默接受
- 帳號：podcast 進度隨帳號刪除；連結 Apple 登入保留 canonical user；OAuth 非 ASCII state 與 provider 錯誤安全處理
- 資料一致：暫存筆記本不可見、已刪除書籍拒絕上傳資產；同名重複卡、並行建立、重複連結收斂；損毀的圖譜／pipeline 資料列 fail closed
- 計費：寬限期優先於過期交易；App Store JWS 解碼錯誤不再洩漏
- 撤回字典卡：官方牌組複製回一般卡片，清除字典複習設定

### Internal
SQLite WAL／生命週期與 store 關閉、ops 取消與 UTC 修正、admin 路由歸屬、Sentry、格式化與測試強化。

## 2.0.3
2026-08-16（`api/2.0.3`，`3480d9cbc`）。

### 摘要（zh-Hant）
帳號刪除會一併清除物件儲存的 library 資產；筆記本刪除可從中斷處續做；App Store 通知保持順序。官方牌組複製曾改為字典卡（2.0.4 撤回）。

### Summary (en)
Account deletion also erases object-backed library assets, notebook deletion resumes from where it was interrupted, and App Store notifications keep their order. Official deck copies briefly became dictionary cards (reverted in 2.0.4).

### Changes
#### Improved
- 筆記本刪除中斷後可續清；App Store 通知排序保留；SQLite 日誌與遷移序列化
#### Fixed
- 帳號刪除清除物件儲存的 library 資產；world-export 單一壞來源不再拖垮整個帳號

### Internal
ops edit WAL 安全備份、seed／user-delete ops primitive、lexical service 邊界拆分。
