<!-- doc-meta
tier: archive
authority: derived
update_trigger: plan-execution
scope:
  - backend/src/kg/
  - ios/BooksAndVocab/
  - ops/
verified_against: frozen
-->

# KG 共享牌組庫（Explore）3-Phase 執行計畫

> **本檔 = 執行分期定稿**（3 個可獨立 commit + 上線的 phase）。把深度規劃的 P0–P4 濃縮為 3 phase。
> **架構深度 SoT = [`2026-07-09-shared-decks-library.md`](2026-07-09-shared-decks-library.md)**（資料模型 schema 全欄、API response model、iOS 檔案錨點、critic 修正、風險全集）。本檔只引其章節（§n），不重述細節。
> **範圍鎖定（執行長 2026-07-09）**：**Phase 1–2 = 官方牌組 only**（唯讀瀏覽 + 複製學習，立即可執行）；**Phase 3 = 社群 UGC**（發布/公開/評分/審核），**out-of-scope、需執行長明確 go**，schema day-one 已保留 forward-compat 欄位、屆時免 migration。
> **執行方式**：`phased` skill，逐 phase TDD（failing test → 綠）+ 逐項 review（鐵律 4），docs-sync 同 PR，所有 Agent 背景執行。

---

## 0. 一頁摘要

**功能**：KG 新增線上共享牌組面：瀏覽官方策展牌組 + 複製來自己學（Quizlet/Anki 風格）。牌組 = Notebook 內容快照；卡片 = Card 的**內容平面**（去 SRS）；複製 = 在自己的 `cards.db` fork 出新卡（fresh id + 預設 SRS）。

**命名（鎖定，不可漂移）**：對外 surface **Explore**（`app.section.explore`）｜後端 package/namespace **`shared_decks`/`SharedDeck`**｜公開路由 **`/api/decks`**｜**禁用 `library`**（已是 EPUB/PDF 書庫）。

**KG 既有地基**：Card = SRS flashcard（`cards/model.py`，7 SRS 欄位 on-row）｜Notebook = deck 容器｜per-user 隔離（每帳號獨立 DB dir）｜guest browse 前例 = Podcast（`PodcastSyncService`）｜官方注入前例 = `build_demo`（SoT→emit→`--check`）。

**3-phase 一覽**：

| Phase | 原 P | 目標 | 獨立上線 | 範圍 |
|---|---|---|---|---|
| **1 地基 + 唯讀官方 browse** | P0+P1 | guest 可瀏覽/預覽官方牌組 | ✅ | 官方 only（鎖定內） |
| **2 複製 + 分享** | P2 | 複製官方牌組進私人 Notebook 即時學 + deep-link 分享 | ✅ | 官方 only（範圍終點） |
| **3 社群 UGC** | P3+P4 | 使用者發布/公開/評分/審核 | — | 🔒 out-of-scope，需 go |

---

## 1. 跨 Phase 架構不變量（三個 phase 都不可違）

1. **中央 `data_dir/shared_decks.db`**（全域，OUTSIDE `users/<uid>/`）：**owner 是 column 非 path**，鏡射 `translate_log` 前例突破 per-user 隔離；永不 reach 進他人 user_dir。詳見 §3。
2. **copy = 內容平面 only + SRS 結構性 reset**：`shared_deck_card` 表**零 SRS 欄位**（發布路徑不可能帶出 7 個 review 欄位）；copy 走 `CardStore.add`（`cards/mutations.py:26`）拿 model 預設 SRS + fresh id。作者排程無 code path 可達複製者。詳見 §2/§4。
3. **官方牌組 = `build_demo` pattern**：git-committed spec SoT → emit 進 catalog，`source='official'`/`owner_id=NULL`/**無登入帳號**；`source` server-authoritative，永不讀 request body（badge 可信性 = 此 invariant）。詳見 §5。
4. **DTO 禁 reuse `CardResponse`**：`DeckCard` 為手寫內容平面子集，型別層省略全部 7 SRS 欄位；contract test 斷言零 SRS 屬性。
5. **doc-sync 鐵律（同 PR）**：`product_surface.md`／`tech_index.md`／`sync_lifecycle.md`／`ops_state_plane.md`／`registry.yml`＋新 `feature_boundary/discover.md`＋`.claude/skills/*` grep-sync；PR 前 `ops/docs_lint.sh`。
6. **iOS gate**：i18n 鐵律 8（零 raw 中文，全 5 lproj）｜Catalyst 雙跑 parity｜Catalog surface + `kg.fixture.dataset.v2` scenario 覆蓋｜VoiceOver/Dynamic Type a11y。

---

## 2. 資料模型（day-one 完整，6 表；schema 全欄見架構 SoT §2）

| 表 | 角色 | 關鍵欄位（摘） |
|---|---|---|
| `shared_deck` | metadata/index plane | id / owner_id(NULL=official) / title / category / language_pair / **source**('official'|'community') / **visibility**(曝光軸) / **status**(moderation 軸) / **is_deleted**(存在軸) / current_version / card_count / cover_pattern / title_nfc_lower / download_count / rating_sum/count / report_count / `UNIQUE(owner_id, source_notebook_id)` |
| `shared_deck_version` | immutable payload | (shared_deck_id, version) PK / content_hash / payload_schema_version |
| `shared_deck_card` | **content plane ONLY（零 SRS）** | content_guid = uuid5(content+pos+mode+meaning，防同形字碰撞) / content/pos/meaning/examples/collocations/note/difficulty/mode/root_form/inflections |
| `shared_deck_rating` | authority | (shared_deck_id, user_id) UNIQUE / stars；`rating_sum/count` 為 denormalized cache |
| `shared_deck_report` | reactive moderation | (shared_deck_id, reporter_id) UNIQUE / reason enum |
| `shared_deck_copy_log` | idempotency + rating gate | (copier_id, idempotency_key) UNIQUE / result_notebook_id |

**三軸刪除狀態仲裁**：`visibility`（private/unlisted/public/official）×`status`（active/under_review/removed）×`is_deleted`（owner soft-unpublish）正交；browse discovery 硬性 `is_deleted=0 AND status='active' AND visibility='public'`。

**Card/Notebook additive 欄位（lazy ALTER）**：`Card.source_shared_card_guid`、`Notebook.source_shared_deck_id/source_version`（provenance）；world-export/seed 必 **omit-if-null** 否則破 `ops_state_plane §1.1` round-trip。

---

## Phase 1 — 地基 + 唯讀官方牌組 browse（原 P0+P1）

> **可獨立上線交付價值**：guest 打開 Explore 就能瀏覽 + 預覽官方策展牌組（含 official badge、卡數）。此 phase 內含兩個 sub-milestone：**1a 全域 store 地基**（無使用者可見面）→ **1b 唯讀 browse**（依賴 1a）。一起成一個可上線 phase。

### Backend（1a 地基）
- `backend/src/kg/shared_decks/store.py`：`SharedDeckStore(path)` SQLModel scaffold（`make_sqlite_engine`＋`metadata.create_all(checkfirst=True)`＋`close()`），**表 class 名全域唯一**；全域單例走 user-independent cache key。
- 6 表全建（含 Phase 3 才用的 rating/report/copy_log 欄位 → forward-compat，免未來 migration）。
- deps 三點接線：`deps.py` `_shared_deck_store()`（仿 `_library_store` deps.py:167）＋ GET=`OptionalCurrentUser`；`app_router_composition.py:60` tuple 加 router；`settings.py` `shared_decks_path` + caps（§6.5 SoT）。
- Card/Notebook lazy ALTER + `NotebookResponse` + wire model + world-export/seed omit-if-null。

### Backend（1b browse）
- `routers/shared_decks.py` mount `/api/decks`；`api_models/decks.py`（camelCase，禁 reuse CardResponse）。
- `GET /api/decks`（guest keyset cursor，filters `q/category/languagePair/official/sort`，只回 public+official）｜`GET /api/decks/{deckId}`（DeckSummary + sample cards）｜`GET /api/decks/{deckId}/cards`（keyset over card id）。
- cursor = opaque base64+HMAC sign；**Phase 1 只露 recency+alpha sort**（popularity/rating 尚無數據，dead-sort 防護）。

### ops（1b 官方內容）
- `ops/official_decks/` git-SoT spec + `build_official.py` emitter（delegate `EditContext`：dry-run/`--commit`/backup/verify）；stamp `source='official'`。
- **notebook-scoped export projection**（world-export 新單 notebook 模式：strip SRS + force is_default=false + assert card_count>0）——publish/官方 spec 前置。
- global-store backup hook（`shared_decks.db` 在既有 per-user backup scope 外，須擴充）。
- seed 1–2 官方牌組進 sandbox 驗證。

### iOS（1b）
- `ContentView.swift:11` 加 `AppPrimarySection.explore`（`app.section.explore`，`safari`/`sparkles`）＋ `:40` gate ＋ `:123` TabView 分支 ＋ `:149` **Catalyst NavigationSplitView 分支（必驗 parity）**。
- **分離 `SharedDeck @Model`**（唯讀 mirror，絕不 reuse `Notebook @Model`）；register 進 ModelContainer + verify lightweight migration。
- `Services/SharedDeckCatalogService.swift` = `PodcastSyncService` 1:1 analog（`optionallyAuthedData` guest browse + **empty-response mass-delete guard** + cover cache logout purge）。
- `Views/Explore/ExploreView.swift`（search + filter chips + 四態 state_matrix + `LocaleAwareFormatter`）＋ `SharedDeckDetailView.swift`（唯讀預覽，**無複製鈕**）。
- Catalog surface 註冊 + fixture SharedDeck seed + 全 5 lproj keys + a11y。

### docs / telemetry
- doc-sync 全套（§1.5）；Sentry breadcrumbs on router + `deck_browse`/`deck_preview` 事件。

### TDD 起點（failing tests）
1. `shared_deck_card` 表**零 SRS 欄位** contract。
2. world-export byte-equal round-trip 加 provenance 欄位後仍過（marketing_account_spec + demo_dataset）。
3. guest 無 token 可列官方牌組；`DeckCard` DTO 無 SRS 屬性；badge = source enum（非 client-settable）。

### DoD
store 建得起 + migration idempotent + round-trip 綠 + backup 涵蓋；guest 可瀏覽/預覽官方牌組（badge/卡數）；iOS Catalog gate 綠、i18n 綠、Catalyst 雙跑綠、docs-sync 綠。**此切片可獨立上線。**

### 依賴
1b 依賴 1a store。無外部依賴。

---

## Phase 2 — 複製 + 分享（原 P2）

> **達成官方牌組庫完整體驗**：瀏覽 → 複製官方牌組進私人 Notebook → 即時複習；public deck 可產生 deep-link 分享。**這是官方 only 範圍的終點。**

### Backend
- `POST /api/decks/{deckId}/copy`（CurrentUser）：server-side clone 進複製者 user_dir——
  - `NotebookStore.create()` 新 notebook（強制 is_default=false、**名稱保證唯一** ← export-trap 防護）；
  - RAW `CardStore.add` loop verbatim 複製內容欄位、**不呼叫 LLM**、SRS 取 model 預設、stamp **strictly-monotonic updated_at**（§4.4 tie-skip 防護）；
  - `shared_deck_copy_log` idempotency（transport retry 不造重複 notebook）；
  - **materialization barrier + 補償式 rollback**（cards.db/notebooks.db 無跨檔 txn，mid-copy crash 不留半成品）；
  - **graph links deterministic remap**（old→new card-id map 寫 `graph_<nb>.json`，零 LLM）；**embeddings 不在 copy 路徑**（改 lazy，避免吞 job-infra）；
  - count-equality 斷言（copied == snapshot，抓 NFC/NOCASE 靜默丟卡）。
- `download_count` atomic increment（`SET x=x+1`，非 Python get-then-set）。

### iOS
- `SharedDeckDetailView` 加「複製到我的牌組」→ destination picker（default 建新 notebook 預填名）＋ **offline copy disabled/queued 態** ＋ copy 後 targeted incremental pull（`fetchNotebooks?since` + `pullCardsToLocal?since`）＋ pending/inserting 態。
- **ShareLink + universal-link handling**（§8.5）：public deck `https://wordnexus.lol/d/{deckId}`（associated domain）→ 開 app 進 `SharedDeckDetailView`；未裝 app → 後端 static landing。
- copied 卡即時可 `startReview`（只吃本地 rows）。

### docs / telemetry
- `sync_lifecycle.md` 記「copy = ordinary batch local creates、fresh updated_at、NO SRS/graph transport」；`deck_copy` 事件（funnel）。

### TDD 起點（failing tests）
1. copy 後複製者卡 SRS = model 預設、fresh id、**無 review_events**。
2. mid-copy crash 無半成品（補償）。
3. 同牌組 copy 兩次後 **world-export 仍成功**（export duplicate-name trap）。
4. clone >page-size 牌組，每卡 **sync down 恰一次**（timestamp-tie skip）。
5. retry copy **不造重複 notebook**（idempotency）。

### DoD
官方牌組可 copy 進私人 Notebook、即時 review、**SRS 隔離契約全綠**、既有 `syncStatus×actionType` 契約結構不變、public deep-link 可分享。

### 依賴
Phase 1（store + browse + 官方內容）。

---

## Phase 3 — 社群 UGC：發布 + 審核 + 評分（原 P3+P4）

> 🔒 **OUT OF SCOPE（執行長已鎖）**：schema/seam 已於 Phase 1 預留（visibility/status/rating/report 欄位 day-one 建好），**本 phase 不實作 write path 與 moderation surface**。要開需執行長明確 go，並承擔 moderation/版權/PII/GDPR erasure 的持續營運成本 + EULA amendment + takedown 承諾。以下為未來啟動時的完整範圍，非本輪工作。

### Backend（未來）
- `POST/PATCH/DELETE /api/decks`（owner-gated、**硬編 `source='community'`**、`UNIQUE(owner_id,source_notebook_id)` republish upsert、原子 version pointer flip、PATCH source-deleted→409、publish guard 拒 0-card/default）。
- **runtime guard**：community publish 強制 `visibility ∈ {private,unlisted}`（不可 public）直到 moderation ready（publish 不可早於 takedown 對 guest 曝光）。
- `POST /rate`（copy-gated one-vote、**Bayesian sort** min-count guard）＋ `POST /report`（Sybil dedup、達閾值 auto-hide、official 豁免、reason enum）＋ `POST /takedown`（admin `get_admin_user`）。
- profanity denylist（title/desc，NFC）；atomic counters；account-erasure 跨 store hook（anonymize owner_id→NULL + display_name→'[deleted]'，已 copy 快照獨立不召回）。

### iOS（未來）
- `PublishSheet`（NotebookCard context menu，visibility default private）＋「我發布的牌組」管理 surface（unpublish 在來源 notebook 刪除後仍可達）＋ provenance 顯示 ＋ rating/report UI（LoginGate，copy 過才可 rate）＋ unlisted `/by-token` deep-link。

### 未來 DoD（分兩段 flip）
- 3a publish（unlisted-only）：owner 可發布/改版/下架，badge 不可偽造，provenance 跨裝置 sync，erasure 觸及全域 store。
- 3b moderation + public flip：sandbox 合成 report→auto-hide→takedown 全鏈綠、EULA+takedown ship、Bayesian rating 上線，**才** flip public UGC（feature flag，須執行長 go）。

### 依賴
Phase 1（schema forward-compat 欄位）+ Phase 2（copy/provenance 基礎）+ 執行長 go + 法務 EULA。

---

## 3. 風險 / 未決 / 升級（濃縮；完整見架構 SoT §10）

**Top 風險（Phase 1–2 內）**：export duplicate-name trap（copy 同名牌組破 world-export，P2 mandatory 名稱唯一）｜timestamp-tie 分頁靜默丟卡（monotonic updated_at + id tiebreaker）｜跨檔非原子 copy（補償式 rollback + barrier）｜copy 冪等（copy_log）｜SRS 洩漏迴歸（DeckCard 手寫子集 + contract test）｜content_guid 同形字碰撞（涵蓋 content+pos+mode+meaning）｜全域 store DR + erasure 在既有 backup scope 外｜SwiftData container 版本（新 @Model + Notebook 加欄，verify lightweight migration）。

**須執行長拍板**：Phase 3 社群 UGC go/no-go（現鎖 no）｜官方牌組生產注入 approval-gated `--commit`（每次 go）｜verified/monetization tier 產品方向。

**未決（out-of-scope v1）**：`.apkg`/CSV interop｜card-level FTS｜上游更新傳播 UX｜push notification｜group/class 可見性｜deck cover image（v1 procedural）｜GDPR data-export。
