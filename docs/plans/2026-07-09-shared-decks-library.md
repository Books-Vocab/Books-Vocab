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

# KG 共享牌組庫（Shared Decks / Explore）建置計畫

> **狀態**：規劃定稿，未執行。由多 agent workflow（6 現況深掃 → 8 架構決策各自設計+紅隊對抗 → 綜合 → completeness critic）產出，critic 抓到的不一致與缺口已逐條定案 fold 回本文。
> **執行方式**：用 `phased` skill，逐 Phase 可獨立 commit + PR，每 Phase 標 TDD 起點與 DoD。所有 Agent 背景執行、逐項 review（鐵律 4）。
>
> **⚑ 範圍定案（2026-07-09，執行長）**：**只做官方牌組（P1-P2）** —— 官方策展牌組的唯讀瀏覽 + 複製學習。**社群 UGC（P3-P4：使用者發布/公開/評分/審核）為 out-of-scope，不承擔 moderation / 版權 / PII / GDPR erasure 的營運成本。** 為避免未來開 UGC 需 migration，**schema 仍 day-one 保留完整 forward-compat 欄位**（visibility/status/rating/report 等），但**不實作**其 write path 與 moderation surface。凡標 🔒P3+ 者即為此次不做、但 schema/seam 已預留的部分。

---

## 0. 一句話與命名定案

在 KG 之上新增一個線上**共享牌組面**：使用者可 (a) 瀏覽官方固定牌組、(b) 發布/分享自己的牌組、(c) 複製他人牌組來自己學（Quizlet / Anki 風格）。

**命名（全計畫鎖定，不可漂移）**：

| 面向 | 命名 | 理由 / 禁區 |
|---|---|---|
| iOS 對外 surface | **Explore（探索）**，L10n key `app.section.explore` | 第 5 個 top-level tab |
| 後端 package / namespace | `shared_decks` / `SharedDeck` | 內部語意清楚 |
| 公開 API 路由前綴 | **`/api/decks`**（定案，移除先前 hedge） | 對外簡潔；內部仍叫 shared_decks |
| **禁用** | `library` 一詞 | `routers/library.py`／`LibraryStore`／`app.section.bookshelf`（localizes "Library"）全是 **EPUB/PDF 書庫**，命名碰撞會混淆 |

**與現有結構的關係**：
- **`Notebook`**（`notebooks.db`，per-user）= 牌組容器，發布時被**快照**。不改它承載 owner/visibility；只加兩個 inert provenance 欄位（`source_shared_deck_id`／`source_version`）。
- **`Card`**（`cards.db`，per-user）= 卡片。其**內容平面**（content/pos/meaning/examples/collocations/note/difficulty/mode/root_form/inflections）可分享；**7 個 SRS 欄位** + `id` + `notebook_id` 是 per-copy，**永不跨界**。
- Bookshelf tab（書庫）與 Notebooks tab 皆不動；Explore 是新增面。

---

## 1. 現況地基（scout 定讞事實，設計依此）

- **Card model**（`backend/src/kg/cards/model.py:16-51`）：單表 `card`，`id`=12-hex uuid4；7 個 SRS 欄位在 Card row 上（`review_interval_hours` default 12.0 / `next_review_at` / `last_reviewed_at` / `review_count` / `lapse_count` / `review_streak` / `last_review_feedback` -1/0/1）。
- **SRS reset primitive 天然存在**：`CardStore.add`（`cards/mutations.py:26`）建 Card 時取 model 預設 SRS + fresh id → **fork-reset 零 code 改動**。`review_events.db` 另存複習事件。
- **Per-user 隔離絕對**：`resolve_current_user`（`user_context.py:110`）算 `user_dir = data_dir/users/<user_id>`，每個 store 是該 dir 內獨立 SQLite（cards.db/notebooks.db/library.db/review_events.db/graph…）。**唯一跨用戶前例** = `translate_log.db`（有 `user_id` column）與 `podcasts/` tree（全域內容供 guest browse）。
- **deps 注入**：`deps.py` 的 `_card_store`/`_notebook_store`/`_library_store(user["dir"])`；`CurrentUser`(143)/`OptionalCurrentUser`(144)/`get_admin_user`(258)。router 掛載在 `app_router_composition.py:60 build_domain_routers()`。
- **iOS 導航**：`ContentView.swift:11 enum AppPrimarySection`（.bookshelf/.podcasts/.notebooks/.overview）同時驅動 iOS `TabView`(123) 與 macCatalyst `NavigationSplitView`(149)；`visibleCases(podcastEnabled:)`(40) 做 feature gate。
- **guest browse 前例 = Podcast**：`PodcastSyncService` 用 `optionallyAuthedData`(170) 唯讀 mirror + empty-response mass-delete guard + cover cache（logout purge）。**這是 Explore 的 1:1 模板**。
- **官方內容注入前例 = build_demo**：`marketing_account_spec.json` / `demo_dataset.json` 走 **SoT→emit→`--check` drift-gate**；`EditContext`（dry-run 預設／`--commit`／auto-backup／verify／audit）。**目前後端無任何 official/curated/shared account 概念**（grep 空）。
- **競品關鍵洞察**：Quizlet/Anki 的分享牌組**皆不帶作者複習排程**（Anki import 明確 reset scheduling）；fork 後預設 **decoupled**（不自動追上游）。Anki `.apkg` = notes + note-types + media + （可選）scheduling。→ KG 對齊：**copy = 內容平面 only、SRS 全 reset、fork 一次性 decoupled**。

---

## 2. 資料模型

### 2.1 中央 store：`data_dir/shared_decks.db`（全域，OUTSIDE `users/<uid>/`）

採 **SQLModel scaffold**（`make_sqlite_engine` + `metadata.create_all(checkfirst=True)` + `close()`），非 translate_log raw-conn 框架（需 indexed search 欄位與正規表）。全域快取用 **user-independent key**。**表 class 名須全域唯一**（避免 `library/store.py` 曾見的 `InvalidRequestError`）。

**`shared_deck`（metadata / index plane）**
```
id                     TEXT PK      # server-minted, ^[A-Za-z0-9_-]{1,64}$（= deep-link 標識）
owner_id               TEXT NULL    # user['id']；official = NULL
source_notebook_id     TEXT NULL    # 作者側來源 notebook（republish 冪等鍵）
title                  TEXT
description            TEXT
category               TEXT         # 粗分類 enum: 'language'|'exam'|'phrase'|'custom'（filter 用）
tags                   TEXT (JSON)  # 細分 free tags
language_pair          TEXT         # 定向對，如 'en-zh'（Card/Notebook 今日皆無 → 發布時填）
source                 TEXT         # 'official'|'community'  ← server-authoritative，永不讀 request body
publisher_display_name TEXT         # 發布當下 snapshot（作者刪帳號後仍可顯示，降級 '[deleted]'）
visibility             TEXT         # 曝光軸: 'private'(default)|'unlisted'|'public'|'official'（TEXT 非 DB enum）
share_token            TEXT UNIQUE NULL  # unlisted 用，secrets.token_urlsafe
status                 TEXT         # moderation 軸: 'active'|'under_review'|'removed'
is_deleted             INT DEFAULT 0     # 存在軸: owner soft-unpublish/delete
current_version        INT          # 指向最新 version（原子翻轉）
card_count             INT
color                  TEXT
cover_pattern          TEXT         # procedural cover（復用 NotebookCoverView）；v1 無 cover image
title_nfc_lower        TEXT INDEXED # 搜尋用，仿 content_nfc_lower（case/diacritic-correct）
download_count         INT DEFAULT 0
rating_sum             INT DEFAULT 0   # denormalized cache（authority=shared_deck_rating）
rating_count           INT DEFAULT 0
report_count           INT DEFAULT 0
created_at / updated_at
UNIQUE(owner_id, source_notebook_id)  # 發布冪等：republish = upsert-in-place
```

**三軸刪除狀態仲裁（critic 修正）**：
- `visibility`（曝光）、`status`（moderation）、`is_deleted`（存在）三軸正交，互不覆寫。
- browse discovery WHERE **硬性**：`is_deleted=0 AND status='active' AND visibility='public'`。
- 轉移：`DELETE`（owner soft-unpublish）→ `is_deleted=1`；`takedown`（admin）→ `status='removed'`；report 達閾值 → `status='under_review'`；`PATCH visibility` 只動 `visibility`。

**`shared_deck_version`（immutable payload plane）**
```
shared_deck_id  TEXT
version         INT
content_hash    TEXT   # 內容平面 deterministic hash，排除 created_at/updated_at
payload_schema_version INT   # 舊 payload replay 多版本容忍
created_at
PK(shared_deck_id, version)
UNIQUE(shared_deck_id, version)  # 並發 republish 靠此 catch IntegrityError（非 threading.Lock）
```

**`shared_deck_card`（content plane ONLY — 零 SRS 欄位，結構性保證）**
```
id              TEXT PK
shared_deck_id  TEXT
version         INT
content_guid    TEXT   # uuid5(NS, f"{content_nfc_lower}|{pos}|{mode}|{meaning_nfc_lower}") ← 涵蓋辨識維度，防同形字碰撞
content, pos, meaning, examples(JSON), collocations(JSON),
note, difficulty(NULL), mode, root_form, inflections(JSON)
UNIQUE(shared_deck_id, version, content_guid)
```
> **無 SRS 欄位是結構性去洩漏**：發布路徑不可能帶出 7 個 review 欄位。**Contract test**：斷言此表零 SRS 欄位、`DeckCard` DTO 零 SRS 屬性、禁任何 `/api/decks` route reuse `CardResponse`。
> **content_guid 修正（critic）**：guid 由 (content+pos+mode+meaning) 衍生而非只 content——否則同形異義（`lead` 金屬 vs 動詞）撞同 guid 被靜默丟卡或 IntegrityError。

**`shared_deck_rating`**（authority）
```
shared_deck_id, user_id, stars(1-5), updated_at
UNIQUE(shared_deck_id, user_id)   # one-vote-per-user
```
> `rating_sum`/`rating_count` 是 denormalized cache，rate 寫入**同 txn 原子更新**；提供從本表 `AVG()/COUNT()` 重算的 repair path。**sort 用 Bayesian average**（min-count guard，見 §6.5）——避免單張 5 星壓過老牌組。

**`shared_deck_report`**
```
shared_deck_id, reporter_id, reason, created_at
reason ∈ {'spam','offensive','copyright','pii','other'}   # enum，非 free-form（critic）
UNIQUE(shared_deck_id, reporter_id)   # 每人一次，防 Sybil 灌報
```

**`shared_deck_copy_log`（idempotency 儲存，critic 補）**
```
copier_id, idempotency_key, source_shared_deck_id, source_version,
result_notebook_id, created_at
UNIQUE(copier_id, idempotency_key)
```
> copy replay 靠此表 lookup 回既有 `result_notebook_id`；也作 rating eligibility gate（copy 過才能 rate，§6.5）。

### 2.2 Card / Notebook 側 additive 欄位（lazy ALTER，無 Alembic）

- `Card.source_shared_card_guid`（nullable）— 走 `cards/schema.py:_migrate_review_columns` ADD-COLUMN pattern。
- `Notebook.source_shared_deck_id` + `Notebook.source_version`（nullable）— 走 `notebook.py:_migrate_columns` pattern。
- **同 PR** 更 `NotebookResponse`（camelCase）+ iOS `Notebook @Model` + `KGNotebook` wire model（provenance 跨裝置 sync）。
- **關鍵坑**：`ops_world_export` / `ops_edit seed` 必 **omit-if-null** 這兩欄，否則破 `ops_state_plane §1.1` byte-equal round-trip（committed spec 無此 key）。加 round-trip contract test。

### 2.3 版本化

Immutable versioned snapshot：publish 凍結內容平面成 `(shared_deck_id, version)` row-set；republish mint **新** version，`current_version` 指標**單 txn 原子翻轉**，舊 version 與已 copy 牌組永不 mutate。`download_count`/`rating_*`/`report_count` 黏 `shared_deck_id`（跨 version sticky reputation，AnkiWeb 行為）。copy 解析到 `current_version`（或 pin version 避免 concurrent republish 撕裂讀）。

---

## 3. 儲存與跨用戶架構

### 3.1 唯一合法的越界方式
共享牌組**必須**住 `data_dir` root 全域 store，**owner 是 column 不是 path**（鏡射 translate_log 前例）。**永不** reach 進他人 `user_dir`。

### 3.2 deps 三點接線
1. `backend/src/kg/shared_decks/store.py` — `SharedDeckStore(path)` SQLModel scaffold；全域單例走 user-independent cache key（入 `_STORE_CACHE` 必 expose `close()`）。
2. `backend/src/kg/deps.py` — `_shared_deck_store()` thin wrapper（仿 `_library_store` deps.py:167）+ `SharedDeckStoreDep`；GET=`OptionalCurrentUser`、write=`CurrentUser`、takedown=`get_admin_user`。
3. `app_router_composition.py:60` — `build_domain_routers()` tuple 加 `shared_decks_router`。
4. `settings.py` — `shared_decks_path`（default `data_dir/shared_decks.db`）+ `shared_decks_publish_enabled` flag + 各項 caps（§6.5）。

### 3.3 官方 vs 社群共存
單一 store／表／browse／copy handler；只有 write 側不同：
- **官方** = ops-shipped git-SoT emitter（`source='official'`, `owner_id=NULL`）。
- **社群** = 使用者 JWT write path，handler **硬編 `source='community'`**，永不從 body/JWT 讀 source。badge 可信性 = 這條 invariant → 專屬 negative test（attacker 送 `source='official'` 被拒/忽略）。

### 3.4 Search index
v1 = metadata-only（title/tags/category/language_pair/card_count/popularity，AnkiWeb 模型），走 `title_nfc_lower`。card-level FTS（找含單字 X 的牌組）留後續 derived index table（non-breaking seam）。

### 3.5 全域 store 的 backup / DR（critic 交叉點）
`shared_decks.db` 在 `data_dir` root，**在既有 per-user backup 工具（`backup_user_dir`/`_is_vocab_file`/world-export/clone-demo）scope 外**。必須：(a) 確認部署 backup 涵蓋 root-level DB；(b) official 注入 subcommand 設 **global-store backup hook**（`EditContext.backup_user_dir` 假設 user_dir，需擴充）。**account-erasure 同一盲點**（§6.4）。

---

## 4. Fork / 複製 / SRS 隔離

### 4.1 Copy 語意（定案：SERVER-SIDE clone，down-sync，一次性 fork）
`POST /api/decks/{deckId}/copy`（CurrentUser）在**複製者自己 user_dir** 內：
1. `NotebookStore.create()` mint 目標 notebook，強制 `is_default=false`，**名稱保證唯一**（碰撞加 `(2)` 後綴 — §4.5 export trap）。
2. RAW `CardStore.add(...)` loop：verbatim 複製內容欄位，**不呼叫 LLM**；7 個 SRS 取 model 預設；stamp **strictly-monotonic-increasing** `updated_at`（§4.4）。
3. stamp `Card.source_shared_card_guid` + `Notebook.source_shared_deck_id/version`（provenance，v1 inert）。

因 clone 寫進複製者正常 `cards.db/notebooks.db`，卡片經**既有 incremental pull**（`pullCardsToLocal ?since` + `fetchNotebooks ?since`）到裝置，作為**已 synced server rows**——永不進 client outbox，故 `syncStatus × actionType` 狀態機（`sync_lifecycle.md` SoT）結構性不受影響。
> **明確刪除** iOS 端「local-create N VocabularyEntry → batchAdd → backgroundSync」路徑：它 re-run LLM enrichment（`KGService+VocabCRUD.swift:143` / `vocab.py:286`）= 雙重 enrich + quota。**Offline copy 不可能**（需連線+auth），UI 須明確 disabled/queued。

### 4.2 SRS reset seam（具體檔案）
兩 seam 皆已存在：**publish 側** snapshot 只含內容平面（`shared_deck_card` 零 SRS）；**copy 側** `CardStore.add`（`cards/mutations.py:26`）取 model 預設 + fresh id。shared store 無 SRS 且 copy 只寫複製者 dir、從不讀作者 `cards.db/review_events.db` → 作者排程無 code path 可達。**不寫 review_events**（clean slate）。
> 語意校正：reset = **new-card** 語意（due 在 now+interval，非立即 due），與手動加卡一致，無 flood。

### 4.3 上游更新傳播（定案：v1 不自動更新，記 provenance 留門）
Fork 預設 decoupled（Quizlet/Anki 規範）。v1 **不做** Anki-style live merge（整套 diff/merge/divergence + note-type brittleness + copier-edit-vs-source race，違無技術債鐵律）。只記 `source_shared_deck_id + source_version + content_guid` 作未來 opt-in「有新版」anchor；更新身分須 scope 為三者聯合，**不可**單靠 content_guid。

### 4.4 時間戳 tie pagination skip（深 bug，須 test）
RAW add loop 複製數百卡 sub-second 完成；若 updated_at 解析度粗，全 N 卡共用時間戳，incremental cursor（`query.py:82/118` keyset over 非唯一 updated_at）在 tie-block 頁邊界 skip 剩餘同時間戳卡 → 大牌組靜默 partial。**修**：copy loop stamp strictly-monotonic updated_at，**且** cursor 加 `id` tiebreaker。Test：clone >page-size 牌組，斷言每卡恰 sync down 一次。

### 4.5 原子性 + 冪等 + 重複卡 + export trap
- **原子性**：`cards.db`/`notebooks.db` 獨立檔**無跨檔 txn**（不可用 clone-demo 的 whole-file stage-swap）。補償式：先 insert notebook 再 cards，mid-loop 失敗 → soft-delete notebook + partial cards；materialization barrier 後才回 200。Test：mid-copy crash 不留半成品。
- **冪等**：`authenticatedRequest` 有 transport retry → 靠 `shared_deck_copy_log`（§2.1）的 `(copier_id, idempotency_key)` dedup，replay 回既有 notebook id。client 每次 copy 動作 mint 一個 idempotency key。
- **重複卡**：永遠複製進**全新空 notebook** → `uq_card_content_notebook`(content COLLATE NOCASE, notebook_id) trivially 滿足；deck 內 dup 由 `CardStore.add` 冪等 skip。跨 notebook 允許重複（一字多牌組，Anki .apkg import 非破壞性 ADD）。加 count-equality 斷言（copied == snapshot）抓 NFC/NOCASE 靜默丟卡。
- **Export trap（最高嚴重度）**：`ops_world_export.py:98` 在兩 active notebook 同名時 raise `WorldExportError`，但 `NotebookStore.create` 零名稱唯一性 → 複製同牌組兩次使帳號**不可 export**（破 backup/clone-demo/§1.1）。**修**：copy 前保證 active-notebook-name 唯一。Test：同牌組 copy 兩次後 world-export 仍成功。

### 4.6 Graph links / Embeddings on copy（定案：內容 + graph remap，embeddings 改 lazy）
copy ships **content plane + graph links（deterministic remap）**；**embeddings 不在 copy 路徑**（critic：避免 Phase 2 吞下 job-infra build）。
- **Graph links**：官方牌組 curated links（marketing spec ≈ 618 卡/318 links）有價值 → copy loop 持 old→new card-id map，寫 `graph_<newnb>.json` 連結 rewrite 到新 id（deterministic、零 LLM，仿 card-move；`ops_shared.notebook_files()` 為 artifact SoT）。
- **Embeddings**：per-notebook、model/dim-guarded（`embeddings_meta_<nb>.json`）→ **不盲複製、不在 copy 時 enqueue**。改 **lazy**：下次該 notebook 需要語意功能（KG 鄰居/graph 生成）時，由既有 per-notebook embedding 生成機制觸發。**成本誠實**：複製牌組在 embeddings 重生前語意降級（無 KG 鄰居），UI 不宣稱「即時完整」。**移除**「copy 完全免 LLM」宣稱（graph remap 免 LLM，embeddings 重生耗 quota 但延後且非 copy 職責）。

---

## 5. 官方固定牌組治理

### 5.1 復用 pattern：git-committed `kg.seed_spec.v1` SoT → emit 進 catalog（無登入帳號）
復用 `build_demo` 的 **SoT→emit→`--check` drift-gate**：
- 每個官方牌組 = `ops/official_decks/` 下 git-committed spec 檔。
- 新 emitter `ops/official_decks/build_official.py` delegate `EditContext`，把 spec seed 成 catalog rows，stamp `source='official'`。
- **不建**專用 official 登入帳號（會與 spec 靜默 drift + 多攻擊面）。curator 可 world-export 拋棄式 scratch 帳號產生初始 spec 再 commit。

### 5.2 Owner / badge
official rows `owner_id=NULL`，badge **純由 `source` enum 驅動**（server-set，永不 client-settable）。丟棄 reserved sentinel publisher_id。badge invariant = verified tier 的 load-bearing security property → 專屬 negative test。

### 5.3 ops CLI 編輯流 / 版本更新
- 新 subcommand `ops_edit publish-official <spec.json>`（`ops_edit_seed_commands.py` + `ops_edit_parser.py`），走 EditContext。
- 生產注入 = approval-gated `--commit`（U6 precedent，無 auto-commit-to-prod，須執行長 go）。
- 兩個 drift check 分開：(a) CI round-trip self-consistency（spec→emit→re-export byte-equal，sandbox，PR gate）；(b) 獨立 pre-deploy prod-parity check（prod host 對 live catalog 跑）。`content_hash` over 內容平面、deterministic ordering、排除 created_at/updated_at；version bump 僅語意變更。
- **notebook-scoped export projection**：world-export 今日 whole-account，須新增**單 notebook 模式**（提一 notebook 的 cards+links 為 content-only spec、strip SRS、force is_default=false、assert card_count>0）。這是 publish 前置，非免費 reuse。
- `language_pair`/`tags`/`category` 為新授權欄位（Card/Notebook 皆無）→ 官方 spec 手填、社群 publish 時擷取。

---

## 6. 可見性 / 審核 / 濫用防護

### 6.1 可見性層級（schema day-one，surface 分期）
`private`(default)/`unlisted`(share_token)/`public`/`official`。無 Quizlet classes/groups（單一學習者 app 無 primitive）。
- 預設 private；publish 為明確可逆 owner 動作。
- discovery query 硬性 `is_deleted=0 AND status='active' AND visibility='public'`；unlisted 僅 `/by-token` 可達、排除 discovery、不 index（obscurity 非 access-control）。regression test 斷言 public browse 對 private/unlisted 回零列。`share_token` 走 `secrets.token_urlsafe`，by-token endpoint rate-limit + constant-status 防列舉。

### 6.2 v1 最小 moderation（reactive + cheap）
- **report** → `report_count` atomic increment + per-reporter UNIQUE → 達閾值 auto-flip `status='under_review'`。
- **admin takedown**（`get_admin_user`）→ `status='removed'`。
- **官方/verified 豁免 auto-hide**（admin-review-only）——否則少數惡意 report 自我 takedown 旗艦內容。
- **profanity denylist** 僅 title/description（NFC-normalized），明確**非** content-safety 保證、非 card content（多語 card 審核不可廉價解、會誤傷正當詞彙）。**此項隨社群 publish 一起在 Phase 3 上線**（critic 排序修正）。
- **content_hash dedup** 鈍化重複 spam。card body PII v1 接受 residual risk，report 兜底。

### 6.3 Rollout gate（誠實版）
`shared_decks_publish_enabled` flag：**Phase 3 community publish 強制 `visibility ∈ {private, unlisted}`（runtime guard 拒 public）直到 Phase 4 moderation ready**（critic：publish 不可早於 takedown 能力對 guest 曝光）。真正測試 = sandbox 合成 report 跑 report→auto-hide→takedown，或 internal canary，**再** flip public UGC。public UGC flip **前**必須：docs/legal EULA amendment + admin takedown 已 ship 並驗證。

### 6.4 Attribution / 授權 / erasure（此決策內定，非 deferred）
Anki-informal：publish 當下 snapshot `publisher_display_name`，顯於卡，無 license 強制，但 publish 時一次性 ToS 接受（授 KG host+redistribute copies 之權）。**account-erasure**：既有 per-user erasure tooling **須擴充觸及全域 shared_decks.db**（critic 補：這是新 code path，非既有 user_dir 刪除能覆蓋）——erasure 時 anonymize `owner_id→NULL` + `display_name→'[deleted]'` + 撤未來 copy 能力；**已被 copy 的快照獨立、不可召回**（takedown 只擋新 copy）。EULA license grant 須相容 statutory erasure。

### 6.5 Rate limit / 併發正確性 + 具體閾值（critic：placeholder → 定數，全進 settings 可調）
| 參數 | v1 值 | 備註 |
|---|---|---|
| `max_cards_per_deck` | 2000 | publish/copy 上限 |
| `publish_rate_limit` | 20 decks / day / user | |
| `report_auto_hide_threshold` | 5 unique reporters | community only；official 豁免 |
| `rating_min_count_for_sort` | 3 | Bayesian prior（防單票灌榜） |
- 所有 counter mutation（report/download/publish-rate）用 **atomic SQL**（`SET x=x+1`），永不 Python get-then-set。
- 跨 worker：module-level `threading.Lock` 不跨 process → 靠 SQLite WAL + busy_timeout + `UNIQUE` catch `IntegrityError`；或部署 `--workers 1` 並文件化此 invariant。
- **rating eligibility**：只有 `shared_deck_copy_log` 有紀錄（copy 過）的 user 能 rate（防 drive-by 灌分）。

---

## 7. Backend API surface

**Router** `backend/src/kg/routers/shared_decks.py` mount `/api/decks`。DTO `backend/src/kg/api_models/decks.py`（camelCase，purpose-built，**禁 reuse CardResponse**）。

| Method | Path | Auth | 用途 |
|---|---|---|---|
| GET | `/api/decks` | Optional（guest） | 目錄瀏覽；keyset cursor over `(sortKey, deckId)`；filters `q/category/languagePair/official/sort`；只回 `public+official` |
| GET | `/api/decks/{deckId}` | Optional | 詳情：`DeckSummary` + 首頁 sample cards + cursor（不回無界陣列） |
| GET | `/api/decks/{deckId}/cards` | Optional | keyset cursor over card `id`（immutable）分頁卡片 |
| GET | `/api/decks/by-token/{shareToken}` | Optional | unlisted 存取；rate-limit + constant-status |
| POST | `/api/decks` | Current（flag-gated） | 發布：body `notebookId+visibility+category?/tags?/languagePair?`；handler 硬編 `source='community'`；snapshot 作者自己 notebook 內容平面 |
| PATCH | `/api/decks/{deckId}` | Current（owner） | metadata/visibility 更新 / re-snapshot（新 version + 原子 pointer flip）；**source notebook 已刪/空 → 409** |
| DELETE | `/api/decks/{deckId}` | Current（owner） | soft-unpublish（`is_deleted=1`） |
| POST | `/api/decks/{deckId}/copy` | Current | server-side clone（§4）+ idempotency key → `{notebookId,cardCount}` |
| POST | `/api/decks/{deckId}/rate` | Current（copy 過） | one-vote-per-user upsert；aggregate 原子更新 |
| POST | `/api/decks/{deckId}/report` | Current | report（per-reporter dedup，reason enum） |
| POST | `/api/decks/{deckId}/takedown` | admin | `status='removed'` |

**Response model 要點**：
- `DeckCard` = `CardResponse` 內容平面子集，**型別層省略全部 7 SRS 欄位** → 洩漏結構性不可能。contract test 斷言零 SRS 屬性。
- `DeckSummary`：deckId/title/color/coverPattern/authorLabel/isOfficial/cardCount/downloadCount/ratingAvg/ratingCount/languagePair/category/tags/updatedAt。
- **keyset cursor** = opaque base64(JSON) + **HMAC-SHA256 sign**（server secret，防竄改，critic）；含 snapshot sort value + immutable tiebreak `deckId`（mutating counter 排序下防 skip/repeat）。
- `deckId` guard `^[A-Za-z0-9_-]{1,64}$`（仿 `NOTEBOOK_ID_PATTERN`）。owner gate = 新 helper（仿 `validate_notebook_access` notebook.py:145，keyed on `owner_id`）。
- **公開 GET 容忍過期 bearer**：degrade 為 guest（或 iOS browse swallow 401），避免開 Explore 時過期 token 觸發 401→session-invalidation 登出。
- publish guard：拒 0-live-card notebook、拒 `default` sentinel、cap `max_cards_per_deck`。

**Doc-sync 義務（同 PR，鐵律）**：`product_surface.md`（feature bullet）、`tech_index.md`（router+每 endpoint+`shared_decks.db` 表+新 settings）、`sync_lifecycle.md`（copy = ordinary batch local creates、fresh updated_at、NO SRS/graph transport）、`ops_state_plane.md`（notebook-scoped export projection + publish-official + §1.1 field-symmetry）、`registry.yml` 新 entry + `feature_boundary/discover.md`、`.claude/skills/*` grep-sync（devops/kg-router）、PR 前跑 `ops/docs_lint.sh`。

---

## 8. iOS UX

### 8.1 導航落點（定案：新 top-level Explore tab，podcast-style 唯讀 mirror）
- `ContentView.swift:11` 加 `AppPrimarySection.explore`（titleKey `app.section.explore`，systemImage `safari`/`sparkles`）。
- `:40 visibleCases(podcastEnabled:)` 加 `.explore` + `exploreEnabled` gate（`Models/KGFeatureFlags.swift`，仿 `podcastEnabled`）。
- `:123` TabView 分支 + `:149` macCatalyst `NavigationSplitView` sectionContent 分支（**Catalyst parity 常見漏點，必驗**）。
- **分離 `SharedDeck @Model`**（唯讀 mirror），**絕不** reuse `Notebook @Model`——否則 public/official 牌組滲進私人 Notebooks `@Query`（scout 首要 failure mode）。

### 8.2 Service / Model（複製 PodcastSyncService verbatim）
- `Services/SharedDeckCatalogService.swift`（NEW）= `PodcastSyncService` 1:1 analog：`optionallyAuthedData` guest browse → fetch list/detail → upsert → reconcile（**empty-response mass-delete guard**）+ cover cache（logout purge via `LocalDataCleanerService`）。
- `Services/KGService+SharedDecks.swift`（NEW）+ `KGServing` protocol：browse/detail/copy/publish/rate/report，走 `authenticatedDecode/authenticatedVoid`；加 test doubles。
- `Models/SharedDeck.swift`（NEW @Model）：remoteId/title/author/verified/tags/category/languagePair/cardCount/downloadCount/rating/**coverPattern/color**（procedural，**非** image path）/updatedAt。**須 register 進 ModelContainer schema** + verify SwiftData lightweight migration（歷史有 teardown/store-wipe 事故，未版本化 container 改動風險 crash/資料遺失）。
- `Models/SharedTypes.swift`：`SharedDeckSummary/Detail` wire（仿 Podcast）；**lenient enum decode** + ignore unknown keys（forward-compat）。
- `Notebook @Model` + `KGNotebook` 加 `sourceSharedDeckId?/sourceVersion?`（lightweight migration）。

### 8.3 畫面流
- `Views/Explore/ExploreView.swift`（NEW）：search field + filter chips（category / language-pair / size buckets / official-vs-community segment / sort），**四態**（loading/empty/error/partial，`state_matrix.md`），counts/dates 走 `LocaleAwareFormatter`。first-run coach 介紹 Explore。
- `Views/Explore/SharedDeckDetailView.swift`（NEW）：預覽（card count / sample cards / author+verified badge / rating / download count）+ 主按鈕「複製到我的牌組」→ destination picker（default 建新 notebook 預填牌組名；「加入既有」需明確 dedup 提示）+ **ShareLink**（產生 deep-link，§8.5）。offline copy → disabled/queued；copy 後 targeted incremental pull，顯 pending/inserting 態。
- publish action 進 `NotebookCardActions` context menu（`NotebookCard.swift:8` / `NotebookListView.swift:387`）→ `PublishSheet`（title/description/tags/languagePair/visibility，**default private**）+ discoverability tooltip。
- **「我發布的牌組」管理 surface**（Phase 3）：讓 unpublish 在來源 notebook 刪除後仍可達（否則 dangling published deck 無法管理）。
- copied 卡即時可 study（`startReview` 只吃本地 card rows）。

### 8.4 Gate / SOP 約束
- **i18n 鐵律 8**：新 View 零 raw 中文；`app.section.explore` + 所有 Explore/preview/copy/publish/rating keys 進**全 5 lproj**；plurals 走 `.stringsdict %lld`；`ops/i18n_lint.sh` 擋。使用者供給的 deck title/publisher_display_name 是 runtime 資料（i18n 覆蓋外）→ 加 render-safety（truncation/RTL/emoji）。
- **Accessibility（critic 補）**：新 surface 全套 VoiceOver labels + Dynamic Type + accessibility traits（rating stars / verified badge / card preview / filter chips），跑 `--ui` a11y test。
- **Catalog coverage gate**：每新 full-screen View（ExploreView/SharedDeckDetailView/PublishSheet）必 register `Debug/CatalogScene.swift` surface + `kg.fixture.dataset.v2` UI-World scenarios（非 `.init` literals），否則 `CatalogCoverageTests` red。須**擴充 fixture** 加 SharedDeck seed data（first-class 工作項）。
- **UI design SOP**（動工前讀）：`docs/sop/ui-design.md` + `docs/reference/ui/{components,review_checklist,state_matrix}.md`；用 design tokens；deck cover 復用 `NotebookCoverView`/`NotebookCard`。
- **LoginGate**：browse 對 guest 開放；copy/publish/rate 走既有 `LoginGateState`/`loginGateSheet`（不 paywall 核心 fork 動作）。

### 8.5 分享 / Deep link（critic 補：feature 名含「分享」，必須實作）
- **public deck**：`https://wordnexus.lol/d/{deckId}` universal link（associated domain，wordnexus.lol 已有）→ 開 app 進 `SharedDeckDetailView`；未裝 app → 後端 static web landing（`static_pages.py` 前例）。
- **unlisted**：`https://wordnexus.lol/d/{deckId}?t={shareToken}` → `/by-token`。
- iOS `ShareLink` 產生 URL；inbound universal-link routing 進 `ContentView` 的 deep-link handler。
- 分配：public link + universal-link handling = **Phase 2**（copy 上線即可分享官方 deck）；unlisted by-token = **Phase 3**（publish）。

---

## 9. 分期 Roadmap

> **執行時以 3-phase 濃縮版為準**：見 [`2026-07-09-shared-decks-3phase-plan.md`](2026-07-09-shared-decks-3phase-plan.md)（P0+P1→Phase 1、P2→Phase 2、P3+P4→Phase 3）。本節 5-phase 為原始細分，保留作架構推導脈絡；phase 邊界與 DoD 執行時按 3-phase 檔。

依賴序：**P0 地基 → P1 唯讀官方 browse → P2 copy+分享 → P3 publish(unlisted-only) → P4 moderation+rating+public UGC flip**。每 Phase 獨立 commit+PR，標 TDD 起點與 DoD。

### Phase 0 — 全域 store + schema 地基（backend/ops/docs）
- backend：`shared_decks/store.py`（SQLModel，unique class names）+ 6 表（deck/version/card/rating/report/copy_log）；deps 三點接線；settings 欄位。
- Card/Notebook lazy ALTER + `NotebookResponse`/wire model + world-export/seed omit-if-null + §1.1 round-trip test。
- ops：global-store backup hook；確認 root-level DB 進部署 backup scope。
- **TDD 起點**：failing test — (a) `shared_deck_card` 零 SRS 欄位；(b) world-export byte-equal round-trip 加欄後仍過。
- **DoD**：store 建得起、migration idempotent、round-trip 綠、backup 涵蓋驗證輸出。

### Phase 1 — 唯讀官方牌組 browse（最小可行切片，可獨立上線）
- ops：`ops/official_decks/` git-SoT + `build_official.py` + `publish-official` subcommand；notebook-scoped export projection；seed 1-2 官方牌組進 sandbox。
- backend：`GET /api/decks`（guest keyset）+ `/{id}` + `/cards` 分頁；DTO。**Phase 1 只露 recency+alpha sort**（popularity/rating 無數據，critic dead-sort 修正）。
- iOS：Explore tab + `SharedDeckCatalogService`（Podcast clone，empty guard）+ ExploreView + SharedDeckDetailView（唯讀預覽，**無複製鈕**）+ Catalog surfaces + fixture seed + 5-locale keys + a11y。
- telemetry：Sentry breadcrumbs on router + `deck_browse`/`deck_preview` 事件。
- **TDD 起點**：guest 無 token 可列官方牌組；`DeckCard` DTO 無 SRS；badge=source enum。
- **DoD**：guest 可瀏覽+預覽官方牌組（badge/count），iOS Catalog gate 綠、i18n 綠、Catalyst 雙跑綠、docs-sync 綠。

### Phase 2 — Server-side copy + 分享官方 deck
- backend：`POST /copy`（idempotency via copy_log、materialization barrier+補償、monotonic updated_at、count-equality assert、graph link remap、**embeddings 不 enqueue**）；`download_count` atomic。
- iOS：「複製到我的牌組」+ destination picker（default 新 notebook、名稱唯一）+ copy 後 targeted pull + pending 態 + offline disabled；**ShareLink + universal-link handling**（§8.5）。
- telemetry：`deck_copy` 事件（funnel）。
- **TDD 起點**：copy 後 SRS=預設/fresh id/無 review_events；mid-copy crash 無半成品；同牌組 copy 兩次後 world-export 仍成功（export trap）；>page-size 牌組每卡 sync down 恰一次（tie skip）；retry copy 不造重複 notebook（idempotency）。
- **DoD**：官方牌組可 copy 進私人 Notebook、即時 review、SRS 隔離契約全綠、既有 sync 契約不變、public deep-link 可分享。

### 🔒 Phase 3 — 使用者 publish（OUT OF SCOPE，schema/seam 已預留，未來開 UGC 才做）
- backend：`POST/PATCH/DELETE /api/decks`（owner-gated、硬編 community、`UNIQUE(owner_id,source_notebook_id)` upsert、原子 version、publish guard、PATCH source-deleted→409）；**runtime guard：community publish 強制 visibility ∈ {private,unlisted}**（§6.3）；profanity denylist（title/desc）；account-erasure 跨 store hook（§6.4）；badge negative test。
- iOS：PublishSheet + 「我發布的牌組」管理 surface + provenance 顯示 + unlisted `/by-token` deep-link。
- **TDD 起點**：attacker 送 `source='official'` 被拒；community publish 送 `visibility=public` 被 guard 拒；republish upsert 保留 download_count；0-card/default notebook 拒；source notebook 刪後 PATCH→409。
- **DoD**：owner 可發布/改版/下架（unlisted 分享），badge 不可偽造，provenance 跨裝置 sync，erasure 觸及全域 store。**public UGC 仍不對 guest 開放。**

### 🔒 Phase 4 — Moderation + rating + public UGC flip（OUT OF SCOPE，同 P3）
- backend：`/rate`（copy-gated one-vote、Bayesian sort）+ `/report`（Sybil dedup、auto-hide、official 豁免、reason enum）+ `/takedown`（admin）；rate-limit；EULA amendment（docs/legal）。
- iOS：rating UI（LoginGate、copy 過才可）+ report 流。
- telemetry：`deck_report`/`deck_publish` 事件。
- **TDD 起點**：public browse 對 private/unlisted 回零列；sandbox 合成 report→auto-hide→takedown 全鏈；re-rate 不 inflate；未 copy user rate 被拒。
- **DoD**：report→auto-hide→takedown 驗證通過、EULA+takedown ship、Bayesian rating sort 上線，**才** flip public UGC（feature flag，須執行長 go）。

---

## 10. 風險與未決

### Top 風險（依嚴重度）
1. **Export duplicate-name trap**（§4.5）— 最高：copy 進同名 notebook 使帳號不可 export，破 backup/clone-demo/§1.1。P2 mandatory 名稱唯一。
2. **Timestamp-tie pagination skip**（§4.4）— 大牌組靜默 partial sync；monotonic updated_at + id tiebreaker + test。
3. **跨檔非原子 copy**（§4.5）— 補償式 rollback + materialization barrier。
4. **Copy 冪等**（§4.5）— transport retry 造重複牌組；mandatory copy_log idempotency。
5. **SRS 洩漏迴歸** — `CardResponse` 洩 7 SRS；靠 `DeckCard` 手寫子集 + contract test，禁 reuse。
6. **content_guid 同形字碰撞**（§2.1）— guid 涵蓋 content+pos+mode+meaning。
7. **Counter 跨 worker race**（§6.5）— atomic SQL + WAL，非 threading.Lock。
8. **Publish 早於 moderation**（§6.3）— P3 runtime guard 強制 unlisted-only，P4 才 flip public。
9. **全域 store DR + erasure 盲點**（§3.5/§6.4）— root-level DB 在既有 backup/erasure scope 外，須擴充。
10. **SwiftData container 版本**（§8.2）— 新 @Model + Notebook 加欄未版本化 → 開既有 store 失敗風險；verify lightweight migration。

### 執行長已定案 / 待拍板
- **社群 UGC publish** — ✅ **已定案：不做**（2026-07-09）。範圍鎖 P1-P2 官方牌組唯讀+copy；P3-P4 out-of-scope，schema forward-compat 欄位保留但 write path/moderation 不實作。未來要開再拍板（含 EULA amendment、takedown 承諾）。
- **官方牌組生產注入**：approval-gated `--commit`（U6 precedent），每次注入須執行長 go。
- **verified/monetization tier**：是否要 Quizlet Verified Creator 類付費/認證層、是否與 billing 互動 — 產品方向，未決。

### 開放問題（明確 out-of-scope v1 / 待需求）
- **`.apkg` / CSV interop**：Anki/Quizlet 互通 import-export，v1 不做（列未來）。
- **card-level FTS**（找含單字 X 的牌組）：延後 derived index table，non-breaking seam。
- **update-propagation UX**（有新版可拉）：v1 記 provenance 留門，merge policy（note-type brittleness）延後。
- **push notification**（copied/rated/taken-down/new-version）：v1 out-of-scope。
- **group/class 可見性層**：單一學習者 app 暫不做。
- **deck cover image**（vs procedural）：v1 procedural；圖像 cover + CDN 列未來。
- **data-export（GDPR）**：published decks/ratings/reports 是否進使用者 data export，待定。
