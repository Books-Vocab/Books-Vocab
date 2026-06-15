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
  - ops/capture_profile.py
  - ops/ui_world_manifest.py
verified_against: 72c31f88
-->
# Ops Product-State Plane（產品狀態控制面）

> 這份不重複 `tech_index.md` 的「什麼指令做什麼」。它管 index 裝不下的三件事:**雙面對齊契約**、**capture_profile 抽象邊界**、**已知結構限制 ledger**。改 `ops_edit` / `ops_cli` / projection / capture_profile 前讀這份,避免重踩已知坑。

`ops_edit`(寫)+ `ops_cli`(讀)不是「截圖假資料工具」,是同一份 production schema 上的讀/寫雙生面,服務 iOS / backend / admin / 截圖 / smoke / support 共用的同一資料世界。`KG_DATA_DIR` 是唯一生產↔sandbox 切換點,注入 sandbox dir 即**結構性**零生產風險(非紀律保證)。

## 1. 讀寫雙面對齊契約(加可斷言欄位前必讀)

兩面**物理隔離、無 schema version；public wrapper 與實作模組已拆開**:

- 寫面 `backend/ops_edit.py` 現在只是 thin wrapper；真正的 command dispatch 在 `backend/src/kg/ops_edit_app.py` + `ops_edit_parser.py` + `ops_edit_commands.py`。實際落地仍走 app per-user store（`CardStore` / `NotebookStore` / `GraphStore`），複用 NFC/dedup/graph merge，不重刻資料寫路徑。
- 讀面 `backend/ops_cli.py` 也是 thin wrapper；真正的 readonly control plane 在 `backend/src/kg/ops_cli_app.py`，再拆成 `ops_cli_parser.py` / `ops_cli_queries.py` / `ops_cli_observability.py` / `ops_cli_costs.py` / `ops_cli_shared.py`。query 已不再塞在單一大檔，但仍是獨立於寫面的讀取邏輯。
- state-diff 的投影面 `project_user_world`（`ops_world_projection.py`）仍是**第三條獨立讀盤路徑**：cards 走 `_load_cards` 動態 SELECT，graph 走 `_load_graphs` 直讀 `graph_*.json`，刻意繞過 GraphStore 快取。

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

## 2. capture_profile 抽象邊界宣告

`kg.capture.profile.v1`(`ops/capture_profile.py`)是**疊在 `ops_edit` 之上的 manifest/orchestration 層**,不是平行系統。`build_ops_edit_commands`(`:201`)把 `materialize{uid,seedFile,steps[]}` 編譯成 `ops-edit seed` + steps 序列,繼承 dry-run/`--commit` gate。截圖(`shots/render/snapshot`)是它的**下游用途之一,不是它的定義**。

`snapshot.datasetFile` 必須是完整 `kg.fixture.dataset.v2` UI World:`load_profile` 委派 `ops/ui_world_manifest.py` 驗證 top-level key set、`datasetID`、asset buckets(`books/audio/images/subtitles/text`)與每個 asset 的 `sourcePath/byteSize/sha256/installAs/contentType`;同時驗 settings auth/entitlements refs、runtime podcast audio/subtitle refs、reader/bookshelf book refs、notebook cover refs、preferred notebook refs,以及 Book `fileName/format` 對齊 asset `installAs/contentType`。source 檔缺失、byteSize/hash 漂移、跨引用缺失或 row↔asset 漂移都直接 fail-fast,不把錯誤延後到 simulator 或 renderer。

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

---
相關:`tech_index.md`(指令/schema 速查)、`product_surface.md`(能力清單)、`docs/sop/architecture.md`(iOS↔backend storage)。
