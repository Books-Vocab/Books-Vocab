<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - backend/ops_edit.py
  - backend/ops_cli.py
  - backend/src/kg/ops_cli_app.py
  - backend/src/kg/ops_cli_parser.py
  - backend/src/kg/ops_cli_queries.py
  - backend/src/kg/ops_edit_app.py
  - backend/src/kg/ops_edit_commands.py
  - backend/src/kg/ops_edit_parser.py
  - backend/src/kg/ops_edit_shared.py
  - backend/src/kg/ops_world_projection.py
  - backend/src/kg/ops_world_expectation.py
  - backend/src/kg/ops_world_export.py
  - ops/capture_profile.py
  - ops/ui_world_manifest.py
verified_against: bb45e0f85
-->
# Ops Product-State Plane（產品狀態控制面）

> 這份不重複 `tech_index.md` 的「什麼指令做什麼」。它管 index 裝不下的三件事:**雙面對齊契約**、**capture_profile 抽象邊界**、**已知結構限制 ledger**。改 `ops_edit` / `ops_cli` / projection / capture_profile 前讀這份,避免重踩已知坑。

`ops_edit`(寫)+ `ops_cli`(讀)不是「截圖假資料工具」,是同一份 production schema 上的讀/寫雙生面,服務 iOS / backend / admin / 截圖 / smoke / support 共用的同一資料世界。`KG_DATA_DIR` 是唯一生產↔sandbox 切換點,注入 sandbox dir 即**結構性**零生產風險(非紀律保證)。

## 1. 讀寫雙面對齊契約(加可斷言欄位前必讀)

兩面**物理隔離、無 schema version；public wrapper 與實作模組已拆開**:

- 寫面 `backend/ops_edit.py` 現在只是 thin wrapper；真正的 command dispatch 在 `backend/src/kg/ops_edit_app.py` + `ops_edit_parser.py` + `ops_edit_commands.py`。實際落地仍走 app per-user store（`CardStore` / `NotebookStore` / `GraphStore`），複用 NFC/dedup/graph merge，不重刻資料寫路徑。
- 讀面 `backend/ops_cli.py` 也是 thin wrapper；真正的 readonly control plane 在 `backend/src/kg/ops_cli_app.py`，再拆成 `ops_cli_parser.py` / `ops_cli_queries.py` / `ops_cli_observability.py` / `ops_cli_costs.py` / `ops_cli_shared.py`。query 已不再塞在單一大檔，但仍是獨立於寫面的讀取邏輯。
- state-diff 的投影面 `project_user_world`（`ops_world_projection.py`）仍是**第三條獨立讀盤路徑**：cards 走 `_load_cards` 動態 SELECT，graph 走 `_load_graphs` 直讀 `graph_*.json`，刻意繞過 GraphStore 快取。
- seed-replay 的導出面 `export_seed_spec`（`ops_world_export.py`，`ops-cli world-export`）是**第四條獨立讀盤路徑**：與 projection 不同，它導出 seed 可**無損重放**的全欄位（含 review 計數器），`connect_ro` + 直讀 `graph_*.json`。它的對齊契約不是 expectation diff，而是 roundtrip 不變量（見 §1.1）。

**後果(結構限制,非 bug)**:寫面寫進 DB 的欄位,讀面/投影面**不保證撈得到**。現在雖然已把 CLI/EDIT monolith 拆成模組,但三面仍各自演進；新增欄位若沒同步到 readonly query 與 projection,照樣會 silent drift。

**verbatim-safe 判準**——一個欄位可被「導出 expectation 並斷言」**當且僅當**:

```
可斷言  ⟺  (ops_edit 直寫)  ∩  (project_user_world projection 有 SELECT surface)
```

寫進 DB **不充分**,projection 必須也撈得到。否則導出的 expectation 會對真讀盤產生 false `missing-key` mismatch。

`project_user_world._load_cards` 當前 surface（PRAGMA 動態裁剪）:
`id / content / meaning / notebook_id / mode / review_count / review_streak / lapse_count / review_interval_hours / next_review_at / last_reviewed_at / source`。

**踩過的坑(回歸測試已固化)**:
- `pos` —— `ops_edit` 寫入但 `_load_cards` 不撈 → 不可導(`test_pos_excluded_not_surfaced_by_projection`)。
- `source` —— seed 裡是 nested object,落 DB 是轉換後字串 → 導 raw 會 false-fail。
- `review` 聚合 / active-notebook(name→id)—— 是 intended transform,導 raw false-fail、導 computed 是 tautology → 一律不導。

**加新可斷言欄位的 checklist**:① 確認 `ops_edit` 直寫該欄(非 store 衍生);② grep `_load_cards`/`_load_graphs` SELECT 確認 projection 撈得到該**原始值**(非 transform 後);③ 在 `ops_world_expectation.py` 的 `_*_VERBATIM_FIELDS` 加欄;④ 跑 real-parity(`test_ops_world_expectation.py::TestRealParity`)→ `mismatches==[]` + tamper 必 FAIL。少任一步 = drift 風險。

防 tautology 鐵則:**derive 只讀宣告 spec,絕不讀 DB**;diff 的 actual 側才走真讀盤。兩條路徑獨立才有鑑別力。

### 1.1 world-export ↔ seed 的 roundtrip 契約（改 seed 欄位 / export surface 前必讀）

`ops-cli world-export <uid> [--out]` 把帳號 vocab 層 dump 成 `ops-edit seed` 相容 spec（`kg.seed_spec.v1`），是行銷帳號**可復現性**地基。它與 seed 之間的不變量（`test_ops_world_export.py::TestRoundtrip` 固化）：

```
seed(spec) → export → seed(新沙盒) → export  ⇒  兩份 export 相等（payload 無 uid/路徑 → byte 相等）
```

支撐這條不變量的設計約束，**改任一面都必須守住**：

- **欄位對稱**：export 導出的每個欄位，seed 必須吃得進去且無損落盤。現況全集 = notebooks(`name/color/cover_pattern/sort_order/is_default`) + cards(內容欄 + `root_form/inflections/is_archived` + review 7 計數器) + links(content 參照)。**給 Card/Notebook 加新欄位時，export 與 seed 要同 PR 對齊**，否則 roundtrip 靜默有損。
- **確定式排序不依賴不可重放值**：排序鍵禁用 created_at / 隨機 id（跨沙盒重放後會變）——notebooks 按 `(sort_order, name)`、cards 按 `(notebook name, content)`、links 按 `(notebook name, from, to, kind)`；datetime 一律正規化 aware UTC isoformat（寫面 naive/aware 落盤不一，export 統一）。
- **review 雙形式**：seed 的 `review` 接 legacy `{state,interval,anchor?}`（語意態，anchor 推導時間，**行為凍結** —— `ops/demo/demo_dataset.json` 等既有消費者依賴）與計數器形式（7 欄直設；`review_count>0` 必帶 `last_reviewed_at`，並經 `synthesize_many` 合成 `review_events.db`，uuid5 event_id 去重冪等）。兩形式混用 fail-loud。export 一律產計數器形式。
- **不可重放資料不進 payload**：孤兒卡（notebook 已刪）、斷鏈 link（端點卡已刪）走 stderr warning，stdout 維持純 spec JSON；active notebook 同名多本、卡 meaning 空白 → export fail-loud（seed 無法重放）。
- **`is_default: true` 映射預設本**：seed 遇 is_default entry 直接更新 id=`default` 的既存預設本（可改名，不增殖新本），否則 export 的預設本重放後會變成第二本普通 notebook、roundtrip 破功。
- **review events 不在 export 範圍**：export 只涵蓋 cards.db 聚合；重放側由計數器重新合成逐筆事件（legacy seed 的世界本來就無事件，重放後會多出合成事件 —— 這是計數器形式的契約，不是 drift）。
- **link 卡對唯一**：app 語意一對卡至多一條 active link（`add_link` 對既存 pair 拋 ConflictError）。legacy graph 同 pair 存多條時，export 確定式保留 sorted 首條、其餘 stderr warning 略過——照導會產出重放時被冪等吸收的 spec，roundtrip 破功（真實案例：000287 divisiveness↔division 雙向兩條）。
- **export 恆唯讀、無 dry-run 語意**：`world-export` 是 ops-cli 讀面指令，沒有 `--commit` 旗標，任何模式下執行都只讀盤（測試以 cards.db sha 不變固化）；「dry-run 才安全」的心智模型不適用也不需要。
- **下游消費者（Phase 2）**：`ops/demo/build_demo.py emit-ios --spec <export產物> --out <path> [--plan <kg.history_plan.v1>]` 把 seed spec 投影成 iOS UI World v2 fixture（投影規則 SoT = `ops/demo/spec_world.py`）。`--plan`（需搭 `--spec`）額外把 review 時鐘凍結在 plan anchor 末刻＝`anchor_day + 24h − max(render_utc_offset) − 1s`，只動 3 個 `review_settings_progress_*` 鍵 × 兩 store（epoch int），其餘 domain byte-equal baseline；validator（`emit_ios._validate_review_clock_overlay`）鎖死只允許這 3 鍵偏離。給 export payload 加/改欄位時，除 seed 對稱外也要確認 spec 投影是否需要跟進（contract 見 `docs/reference/tech_index.md` fixture 契約段）。

## 2. capture_profile 抽象邊界宣告

`kg.capture.profile.v1`(`ops/capture_profile.py`)是**疊在 `ops_edit` 之上的 manifest/orchestration 層**,不是平行系統。`build_ops_edit_commands`(`:285`)把 `materialize{uid,seedFile,steps[]}` 編譯成 `ops-edit seed` + steps 序列,繼承 dry-run/`--commit` gate。**`snapshot.source=spec-emit` 模式 `materialize` 缺席**（world 由 `specFile`＋選配 `planFile` 確定式派生），改走 `build_emit_commands`(`:354`)/`emit_spec_world`(`:398`) on-demand emit 到 gitignored `build/capture_profiles/`,不繼承 ops-edit 寫入面。截圖(`shots/render/snapshot`)是它的**下游用途之一,不是它的定義**。

`snapshot.source=dataset-file` 時 `snapshot.datasetFile` 必須是完整 `kg.fixture.dataset.v2` UI World（`source=spec-emit` 時 datasetFile 缺席，world 由 spec on-demand emit 為同 schema 產物，再走同一驗證）:`load_profile` 委派 `ops/ui_world_manifest.py` 驗證 top-level key set、`datasetID`、asset buckets(`books/audio/images/subtitles/text`)與每個 asset 的 `sourcePath/byteSize/sha256/installAs/contentType`;同時驗 settings auth/entitlements refs、runtime podcast audio/subtitle refs、reader/bookshelf book refs、notebook cover refs、preferred notebook refs,以及 Book `fileName/format` 對齊 asset `installAs/contentType`。source 檔缺失、byteSize/hash 漂移、跨引用缺失或 row↔asset 漂移都直接 fail-fast,不把錯誤延後到 simulator 或 renderer。

**何時用 capture profile**:需要「造景 → verify(world-diff)→ snapshot → render」**可重現串接**、需要 derive-expectation 做 drift guard、或要進 CI/行銷流程的場景。

**何時裸 `ops-edit` 就好**:一次性 support 重現、單帳號臨時造景、不需 expectation/render 的探索性操作。別為單發操作硬套 profile。

**steps transform 的覆蓋邊界**(`ops_world_expectation._derive_config`,`:80-97`):
- **能導**:`user-config-set --review-clock paused|running` → `review_clock.is_paused`。
- **刻意不導**:`--active-notebook`(name→id 解析,`:84` 註解)、`--sort-order`(projection 無 surface)、`--auto-link`(trivially derivable 但目前無 scenario 斷言需求;要導時擴 `_derive_config` 即可)。這些 step 仍會真執行落地,只是不進導出的 expectation——靠 real-parity 的真讀盤側驗證,不靠靜態斷言。

要擴 scenario 能力,**擴 `materialize.steps[]` + `derive_expectation` 的 transform 建模**,不另起爐灶。

## 3. 已知結構限制 ledger（疊 scenario 層前須知）

| # | 限制 | 現況 | 證據 / 須知 |
|---|------|------|------------|
| ① | 跨檔交易 + 單帳號快照含 identity | **已補** | 單帳號 backup 內嵌該 uid 的 `users.json` record + scoped email_index；`restore` 能一起回復 config/identity。原「users.json 不在 tar」破口已關。 |
| ② | 整世界 snapshot/restore | **已補** | `world-snapshot` / `world-restore` 已進 control plane；`backup_world` 含 `users.json`，落 `_ops_world_backups/`。 |
| ③ | 讀寫不對齊 | **仍在(結構)** | 寫面 store / 讀面模組化 query / 投影面第三路徑，仍無共用 schema version。見 §1。state-diff 必經 `project_user_world` 自定義投影。 |
| ④ | 冪等語意不一致 | **仍在(刻意)** | `link-add` 冪等但**不更新** confidence/kind/reason，只有 `--if-exists update` 會覆寫；`seed` 是 upsert 覆蓋核心欄；`clone-demo` 是全覆蓋先清後換。三種重跑語意不同，造景前要知道你在用哪種。 |
| ⑤ | graph = per-notebook JSON + 快取 | **仍在(設計)** | `_load_graphs` 直讀 `graph_*.json` 繞快取。任何 graph 斷言/驗證**必讀磁碟**，不可信 GraphStore in-memory 態。 |
| ⑥ | clone-demo 綁來源真實內容 | **仍在(本質)** | byte-clone 來源 vocab 層,可重現需 `--expect-source-fingerprint` 鎖來源 uid,否則來源漂移會改 clone 結果。 |

③④⑤⑥ 不是待修 bug,是**疊 scenario/replay 層時要繞開或顯式處理**的已知地形。補坑優先序由實際 world-reset 需求決定,不為補而補。

## 4. 官方牌組注入 emitter（build_official.py）入口偏差宣告

共享牌組庫（Explore）的官方內容注入走**獨立 emitter** `ops/official_decks/build_official.py`，**不是** `ops_edit` subcommand——仿 `ops/demo/build_demo.py` 的 SoT→emit→`--check` drift-gate 範式（git-committed `kg.official_deck.v1` spec → emit 進全域 `shared_decks.db` catalog、`source='official'`/`owner_id=NULL`）。

**為何不掛 `ops_edit`（入口偏差理由）**：

- `ops_edit` 的 `EditContext` 假設 **per-user `user_dir`**（backup/verify/audit 全繞 `backup_user_dir`）；`shared_decks.db` 是 **root-level 全域 store**（OUTSIDE `users/<uid>/`），不在該 scope 內。`build_official.py` 改走 `backup_world`（label `shared-decks-official`，涵蓋 root-level DB）+ 手動 `append_audit`（schema `kg.official_deck_injection.v1`），複用 `EditContext` 的 dry-run 預設 / `--commit` gate 契約精神，但不硬套 per-user 假設。生產注入 approval-gated（U6 precedent），不 auto-deploy。
- 對齊 `build_demo`：官方策展內容與 demo 帳號同屬「git-SoT → emit → `--check`」家族，語意一致、各自獨立 emitter，不與 `ops_edit` 的 per-user 讀寫雙面混淆。

**notebook-scoped export projection（world-export 單 notebook 模式）—— Phase 1 deferred**：架構 SoT（`docs/plans/2026-07-09-shared-decks-library.md §5.3`）原列「world-export 新增單 notebook content-only 模式（strip SRS + force `is_default=false` + assert `card_count>0`）」作發布前置。Phase 1 **刻意不實作**：

- 官方 spec 是 `kg.official_deck.v1`（直接描述 deck content plane），與 `world-export` 產出的 `kg.seed_spec.v1`（§1.1，整帳號 vocab 層 replay spec）**shape 不同**——不是免費 reuse。
- curator 產 spec 是**一次性便利**（可 world-export 拋棄式 scratch 帳號、手動裁剪成 official spec 再 commit），**非 consumer-facing blocker**；不值得在 Phase 1 為它擴 `world-export` 投影面。
- 要做時擴 `ops_world_export.py` 加 `--notebook <id>` content-only 模式，仍須守 §1.1 的欄位對稱與確定式排序不變量。

---
相關:`tech_index.md`(指令/schema 速查)、`product_surface.md`(能力清單)、`docs/sop/architecture.md`(iOS↔backend storage)。
