# KG Workspace Agent Guide

> 🖥 **雙機專案（managed_on: both）**：本 repo 兩台都有 clone，正式站 wordnexus.lol + iOS build 在常駐機（ssh chenliangyu@100.118.39.104）。雙機架構/ssh/gh 互通/部署回滾完整指引見 ~/project/AGENTS.md「雙機體系」段與 ~/butler/docs/kg-backend-deployment.md。先 hostname -s 定位。

## Identity

**KG = Knowledge Graph 英語詞彙學習 app** — EPUB/PDF/TXT/MD reader 選詞 → 翻譯 → 詞庫 → 知識圖譜 → today review → podcast。  
Monorepo:`ios/`(SwiftUI BooksAndVocab app)+ `backend/`(FastAPI / Python,含官網)+ `lab/`(Podcast monitor / Claude Code Gateway 等)+ `ops/` + `docs/`,單一 `.git`；`frozen/2026-06-14-web-chrome-parity/` 收納已冷凍的 web pilot / Chrome extension / web-chrome parity tooling。

| key | value |
|-----|-------|
| project key | `kg` |
| backend | `backend` |
| ios | `ios` |
| remote | `~/knowledge_graph_api` |
| domain | `wordnexus.lol` |
| container | `knowledge-graph-api` |
| port | `8000` |
| commit prefix | `ios:` / `api:` / `ops:` / `docs:` |

## 組織模型（營運憲法，always-on）

本工作區用「公司」隱喻運營,但**採相對定址,不用絕對層級**。

**核心原則:沒有「我在第幾層」。** 每個節點只認識兩個鄰居——**上一階**(委派我、我交 receipt 的對象)與**下一階**(我委派、向我回報的對象)。同一套委派契約在每條邊上遞迴套用,深度無限且無關緊要;插入或移除中間節點,都不必為任何人重新編號。

**唯一固定錨邊**:執行長(使用者)→ 總經理(本主線)。使用者只跟總經理對話。其餘所有邊全是遞迴展開,無絕對座標。

**每條委派邊的契約(到處相同)**
- **下行 = task brief**:目標 / 驗收條件(DoD)/ 邊界 / 必讀 SoT 指標 / 回報格式。
- **上行 = receipt**(`kg-receipt`):驗證輸出 + 交接點。
- 每個節點**同時**是上一階的受派者、下一階的委派者。人例外(只委派);葉節點本回合只受派,需要時仍可開下一階。

**節點自我認知只問三件事(永不問「第幾層」)**
1. **上一階是誰** — 我對誰負責、向誰交 receipt。
2. **我的範圍與 gate** — 我獨佔的 definition of done。
3. **我能派哪些下一階** — 可委派的 `.claude/agents/*` custom agent / worker。

**總經理職位說明書**(總經理 = 上一階為執行長的節點,同樣遵循上述遞迴契約;其特有職責:)
- **做**:意圖翻譯、拆 WBS、選部門與派任形狀(fan-out / pipeline)、品管 gate、整合驗證、回報。
- **不做**:domain 實作粗活——一律下放給部門 custom agent(呼應鐵律5「所有 Agent() 背景化」)。
- **唯一親自處理**:跨部門整合衝突,以及判斷是否升級給執行長。

**升級給執行長的觸發(其餘總經理自決後告知)**:不可逆生產操作 / 預算·成本 / 策略分岔(多路皆合理且影響大)/ 安全紅線 / 真正的歧義。

**全知 ≠ 全在場**:總經理的全局觀來自讀**檔案室(SoT docs)+ 回報(receipt)**,非微觀監工每個 agent 的 context。

**部門名冊**:`.claude/agents/` 目錄本身即名冊(`ls` 是清單,frontmatter `description` 是職責),**不另立手寫 roster 檔**。

**SoT 零重複鐵則**:一個事實只有一個 owner 文檔(registry 標 `authority: SoT`);CLAUDE.md、agent 檔、流程文檔只能用 path / registry id / 鐵律編號**指過去,絕不複述**。

**自我提升迴圈**:摩擦走 andon → receipt 強制表態(規則見 `kg-receipt`「Tooling Debt」)→ `docs/runbook/backlog/<id>.json`(SoT,一筆一檔;入口一律 `ops/backlog.py`,**機器一律讀 store**:`list --json` / `show`。單一檔案的 markdown view 已移出版控——它是 `render --commit` 現地產出的方便產物,不是任何人的資料來源,見 IMP-20260807-b9526c)→ triage 到 resolved(連 commit = 可回溯)。**兩條 stream、兩個 owner**:`--stream IMP`(工具 / CLI / 文檔 / 架構摩擦)→ `platform-steward`;`--stream APP`(會出貨給使用者的缺陷,另附 `--surface` / `--repro` / `--build`)→ 對應 Line 部門(`ios-engineer` / `backend-engineer`)。分流看**這缺陷誰碰得到**(使用者 vs 只有 repo 內的人)不看誰發現,可判定判準見 `kg-receipt`「Stream 分流」。無聲妥協(硬幹)違鐵律9;升級階梯見 `docs/sop/agent_org.md`。

## ops 資料工具（always-on，不靠 skill 觸發）

凡需要**查詢或修改**用戶資料、單字庫、額度、config、graph、cost，一律用 CLI，**禁止讀 ops/*.py 原始碼後自行拼 SQL 或直接操作檔案**。

```
# 唯讀查詢
(cd backend && uv run python ops_cli.py <subcommand> [args])

# 寫入（dry-run 預設，--commit 才落地）
(cd backend && uv run python ops_edit.py <subcommand> [args])
```

不確定有哪些子指令 → `(cd backend && uv run python ops_cli.py --help)` / `(cd backend && uv run python ops_edit.py --help)`。生產資料操作仍優先走 `./ops/devops_kg_safe.sh ops-cli|ops-edit ...`;完整子指令表與安全契約在 `devops` skill 內。

## llm_eval 工具（always-on）

LLM prompt 評估 / 語料管理統一入口：

```
cd lab/llm_eval && uv run python scripts/cli.py <subcommand> [args]
```

子指令：`eval` / `prompts` / `datasets` / `providers` / `corpus-build` / `gold-queue`。`--help` 查完整用法。**禁止讀 llm_eval/*.py 原始碼後自行拼 API 呼叫**。

## 對話啟動流程

1. **掃描 skill 觸發條件** — 對照使用者第一句話,凡符合已註冊 skill 的觸發描述,立即 `Skill()` 載入。「不確定是否符合」= 符合；若任務是新對話接手、找入口、跨 docs/ops/iOS/backend/podcast/release,優先觸發 `kg-router`。
2. **確認 scope** — 任務是否 project-scoped。若涉及跨專案,切回 repo root 遵循根 `CLAUDE.md`。
3. **載入文檔控制面** — `docs/registry.yml` 是活文檔 SoT;先用下方「Docs Control Plane 快速用法」判斷該讀 / 該同步 / 該驗什麼。
4. **依任務性質判斷是否需要 deep scan** — 模糊請求(「看看現況」「整理一下」「有什麼可以做」)才 dispatch 2-5 個 general-purpose agent 平行掃描;具體任務(typo / 單檔修改 / 已指明範圍)**不要** deep scan。

## Docs Control Plane 快速用法

目標:讓 agent 一進 repo 就知道文檔怎麼查、怎麼同步、怎麼驗證。

- **先看 registry**:`docs/registry.yml` 是機器可讀控制平面。每個 entry 的 `id/path/kind/authority/triggers/sources/generator` 定義 owner、觸發條件、path hint 與生成器。`sources` 的 `!path` / `!glob` 是排除 broad source 下的已知誤報。
- **做改動前查 impact**:`./ops/docs_impact.py --since <base>` 或 `./ops/docs_impact.py --files <path...>`。輸出是候選文檔,不是自動更新命令;用 `triggers` + 實際 diff 判斷是否需同步。
- **日常 PR gate**:`./ops/docs_lint.sh`。預設只驗 registry + changed docs,並印 registry impact hints(warn-only)。只驗控制面用 `./ops/docs_lint.sh --registry`。
- **全 repo 健康盤點**:`./ops/docs_lint.sh --audit` 或 `--all`;這是 health audit,不是日常 PR gate。
- **coverage debt**:`./ops/docs_registry_coverage.py` 看哪些 linted docs 尚未進 registry,並分成 `active_unregistered`(應補進控制面)與 `backlog_unregistered`(archive/plans/specs/snapshot 等非日常 gate debt);`--strict` 只卡 active-doc 覆蓋 debt,不等同日常 gate。
- **同步流程權威**:背景 doc-sync agent 讀 `docs/sop/doc_sync.md`;人工維護/狗食流程讀 `docs/sop/docs_dogfood.md`。

## Skill 系統(KG 專屬 9 個 + plugin 全域可用)

| Skill | 觸發 | 用途 |
|-------|------|------|
| `kg-router` | 新對話接手 / 找入口 / 跨 docs、ops、iOS、backend、podcast、release 的任務 | 冷啟動路由：讀 capability matrix / docs registry / product+tech index,再載入最小必要 skill |
| `kg-docs-control-plane` | docs impact / docs lint / registry / verified_against / agent-facing surface 同步 | 文檔控制面判讀與 gate |
| `kg-receipt` | handoff / receipt / 驗證證據 / 任務收尾格式 | 固定輸出完成證據與下一輪接手資訊 |
| `app-debug` | bug / test failure / 異常行為 | 根因調查 + 平行假說驗證 |
| `devops` | 部署 / 狀態 / 用戶查詢 / 額度 / 遠端操作 / 維護 | 生產環境運維全覽 |
| `billing` | 「這月花多少」/ cost / 帳單 / drift / 升降 bundle / token 燒多少錢 | 三源(AWS/GCP/內部 LLM)對齊 + 月度盤點 + read-only 建議 |
| `data-analysis` | 分析用戶 / 圖譜 / 連結 / 額度 / 嵌入 / 閾值調優 | 深度資料分析 |
| `worktree-flow` | 新 session 丟 debug/dev/research intent 且要在隔離 git worktree 開發到 merge 進**本地** main；任務宣稱「需要在 main 上做」；發布上生產 | 隔離工作樹 intent→cutover→deploy 全流程，編排 `ops/worktree_orchestrate.py` 原語（preflight/open/adopt/gate/catchup/land/cutover/resolve/sync/deploy/sync-main/freeze）。**拓樸=本地 main 為主幹，三平面**：worktree fork 自本地 main、cutover=develop **離線 ff 本地 main**（不 push 不部署），本地 main 超前 origin；`sync`=backup（推 origin/main 備份、reconciler 不看 main=零生產副作用）；要上生產才 `deploy`=release（推 **origin/prod**=觸發 felix reconciler 部署，唯一碰生產），語意見 `docs/sop/release.md`。工作樹健康是**流程內生不變式**：每條完成即 cutover 即 resolve 即自清，preflight sweep 收流程外崩潰殘骸。「需要 main」路由：bootstrap 悖論→`adopt`、repo 手術→`freeze`、剛 clone/felix 部署機追 origin→`sync-main`。（**已退役** `converge`/`promote`。） |
| `podcast` | EPUB → podcast pipeline | 深度分析 → 規劃 → 腳本 → TTS → 字幕 |

**另有 plugin skill 全域可用**(`phased`(多步驟 feature / refactor / bugfix 的結構化執行入口 — 切 phase + 邊做邊 review N-1)、`anthropic-skills:*`、`review`、`verify`、`run`、`code-review`、`init`、`schedule`、`loop`、`update-config` 等),觸發描述見 system reminder。

### 規則
- 觸發條件符合就**立即** `Skill()` 調用,不問使用者。多個同時符合則全部載入。
- **所有 Agent() 一律 `run_in_background: true`。無例外。**

## 鐵律(全域,9 條,不可繞過)

> **執行力標註（2026-08-03 起）**：每條標 `[machine]` / `[prompt]` / `[text-only]`。
> agent 的偏執程度是照「宣稱的執行力」校準的——九條讀起來一樣硬，就會在其實沒人守的
> 地方放鬆警戒。`[machine]` = 有工具會回非零擋下；`[prompt]` = 只在 agent/skill 檔的
> 指示裡，靠自律；`[text-only]` = 只存在於本檔。**標註本身是可稽核的事實，不是評價**；
> 執行點變了就同步改標註。


1. **TDD** `[prompt]` — failing test → 紅 → 最小實作 → 綠。不可跳過。
2. **驗證先於宣稱** `[machine]`(cutover 要求綁 HEAD 的新鮮非-block verdict:`worktree_orchestrate.py:cmd_cutover`;receipt 層仍是 `[prompt]`) — 說「完成 / 通過 / 修好」前必須有當下驗證輸出。「should work」= 謊言。
3. **根因先於修復** `[prompt]` — 遇 bug 必須確認根因才動手。不可看到錯就補 patch。
4. **逐項 review,不批次** `[machine]`(commit receipt 由 `ops/review_audit.sh` 在 cutover gate 驗;它只驗 trailer 存在且合法,不驗 review 品質——那部分是 `[prompt]`) — 每完成一個 fix/feature 立即 dispatch review agent,PASS 才下一個。禁「全部寫完再一起 review」。適用所有程式碼修改。
5. **長時操作背景執行且不可靜默** `[machine]`(`ops/lib/streaming_command.py` 的 heartbeat 契約,worktree gate / app_review_evidence / ios_ops 共用;「所有 Agent() 背景化」那半條是 `[prompt]`) — 任何 `Agent()` 與耗時 Bash(`ios_ops.sh build`/`test`、backend `pytest`、deploy/rsync、長下載/install)一律 `run_in_background: true`。**主線不阻塞**,完成由 notification 觸發。背景 agent 啟動後立即回報 phase/agent id/status，driving agent 最長每 20 秒輪詢並提供可見進度；長 command 啟動後立即回報 phase/PID，執行中最長每 20 秒回 elapsed/PID/alive，正常結束時回 phase/duration/exit status。若既有工具沒有 heartbeat，先補工具或用外層監看補足，禁止讓使用者靠猜測判斷是否卡死。
6. **主動查文檔(Doc Lookup Discipline)** `[text-only]` — 涉及 endpoint / 模組 / env var / DB schema / 既有 feature / ops 工作流,**判斷「這需要查一下」就立即讀對應 reference,不靠記憶**。dispatch 有複雜度的工作時,prompt 必須明示「拿不準就讀 doc,不要省 token」。純樣板修改(typo / rename)不適用。
7. **生產禁用指令** `[machine]`(`ops/devops_kg_safe.sh:is_blocked_run`;注意 `ops-cli`/`ops-edit`/`container-script` 是 argv pass-through,不經此閘,安全model改由工具內部 dry-run/備份/verify 承擔) — `docker compose down -v` / `docker system prune -a` / `rm -rf /home/ubuntu/*`(涵蓋 data dir)永遠禁止。運維走 `ops/devops_kg_safe.sh`,不繞過 wrapper。完整見 `docs/policy/safety.md`。
8. **禁止 iOS raw 中文字串** `[machine]`(CI `ui-quality-gate` + cutover `ui-quality-fast`,兩處皆 `--baseline-check`;baseline 自 2026-08-03 起為 0=零容忍,由 `ops/tests/test_lint_baselines.sh` 釘住不得鬆弛) — `Text("中文")` / `Button("中文")` / `.navigationTitle("中文")` 由 `ops/i18n_lint.sh` 擋。所有 user-facing 字串走 `L10n.string(_:)` / `L10n.format(_:_:)`。豁免用行內 `// i18n-allow: <reason>`(品牌名、人名、ASCII-only 技術 ID)。詳見 `docs/sop/i18n_lint.md`。
    - **(待 Phase 3.1 後生效)** Static `DateFormatter` / `RelativeDateTimeFormatter` / `NumberFormatter` 走 `LocaleAwareFormatter`。lint 現以 baseline 模式追蹤,strict 模式由 Phase 7.1 Xcode Run Script 啟用。
9. **工具摩擦優先修工具** `[prompt]` — 當 agent 使用既有工具完成工作流時遇到挫折、不順、輸出不自解、help 失準、入口漂移或會誘導繞路,先第一性原理判斷工具/文件/skill 哪裡壞。小問題可記入 receipt 的 tooling debt 並回到原目標；中大型問題或會導致誤判/繞過工具的問題,立即停下來修工具並驗證,再回到原本任務。

## Commit / 落地政策

- **Worktree / feature branch 任務**:驗證全綠(測試 / lint / build / drift 等有**當下輸出**)後 **直接 commit + 走 `cutover` 落地本地 main,不先問**,事後簡述決策與理由(使用者長期授權,2026-06-04)。
  > 授權本身一字未動;改的只是它指向的機制名——原文指向的 PR 合併入口已被拆除。落地語意見 `docs/sop/release.md`,理由見 `IMP-20260805-34f30f`。
- commit message 用 Identity 表 prefix(`ios:` / `api:` / `ops:` / `docs:`);邏輯獨立改動分開 commit。

## Scope 規則(觸發式,非 always-on)

- **改 iOS View / UI** → 動手前讀 `docs/sop/ui-design.md`(規範) + `docs/reference/ui/components.md`(現有元件) + `docs/reference/ui/review_checklist.md`(自查 5 項) + `docs/reference/ui/state_matrix.md`(狀態覆蓋);對應 feature scope 另讀 `docs/reference/feature_boundary/<reader|vocabulary|notebook|bookshelf|podcast|settings>.md`。
- **iOS 驗證** → 統一入口 `./ops/ios_ops.sh build` / `./ops/ios_ops.sh test`(底層 `ios_build.sh`/`ios_test.sh`/`ios_release.sh` 共享 `shlock` 鎖,多 worktree 安全);細節見 `docs/sop/ios.md`。現在 `ios_test.sh` 已有 unit/UI/all-targets scope、heartbeat、log preserve、false-green 防護與 DB lock retry,所以改 iOS code/test 時**主動跑最小足夠測試**:先用 `--file`/`-g`/method 重現與驗證局部;改 UI/navigation/accessibility 時用 `--ui` 精準測;跨 feature / test infra / release / cleanup 收尾才跑 `--all-targets`。`ios_ops.sh build` 仍作為編譯 gate,不以 build 取代相關測試。
- **改 user/agent-facing 介面**(`backend/ops_*.py`、`backend/*_cli.py`、admin endpoint、CLI subcommand、env var、設定 schema) → **同 PR 內**grep `.claude/skills/`、`docs/reference/product_surface.md`、`docs/reference/tech_index.md`、`docs/sop/`、`docs/policy/`、`docs/runbook/`,凡引用到舊命令/欄位/旗標清單立即同步。下個 agent 不知道新功能 = 任務沒閉環。Review agent prompt 必須含此項檢查。

## Doc 路由(語意 → 路徑)

不確定該讀哪份時對照本表。標 **(SoT)** 的衝突時權威。

| 我正在做 | 先讀 |
|---|---|
| 查功能是否已實作(避免重造) | `docs/reference/product_surface.md` **(SoT)** |
| 查 endpoint / DB table / env var / iOS 模組叫什麼 | `docs/reference/tech_index.md` **(SoT)** |
| 改 `ops_edit`/`ops_cli`/projection/capture_profile(加可斷言欄位 / 疊 scenario 層 / 防雙面 drift) | `docs/reference/ops_state_plane.md` **(SoT)** |
| 改 iOS Reader 任何檔案 | `docs/reference/feature_boundary/reader.md` |
| 改 iOS Vocab / Sync / TodayReview / KG | `docs/reference/feature_boundary/vocabulary.md`(scope map) + `docs/reference/sync_lifecycle.md` **(SoT)**(狀態流轉) |
| 改 iOS Notebook(list / card / cover / edit sheet) | `docs/reference/feature_boundary/notebook.md` |
| 改 iOS Bookshelf(書架 / 播客 series 列表 / 匯入) | `docs/reference/feature_boundary/bookshelf.md` |
| 改 iOS Podcast player / 字幕 / progress | `docs/reference/feature_boundary/podcast.md` |
| 改 podcast 生成 pipeline(`lab/podcast/` / synthesize / subtitle / TTS / upload) | `docs/sop/podcast_pipeline.md` |
| 改 iOS Settings | `docs/reference/feature_boundary/settings.md` |
| 改 CSV / Card schema | `docs/reference/card_format.md` **(SoT)** |
| 改 sync 狀態流轉(`syncStatus` × `actionType`) | `docs/reference/sync_lifecycle.md` **(SoT)** |
| 寫 backend test | `docs/reference/testing/backend_strategy.md` |
| 發版前 smoke(15 分鐘) | `docs/reference/testing/smoke_checklist.md` |
| 部署 / 用戶查詢 / 額度 / 遠端 / 維護 | 觸發 `devops` skill(內含 SOP) |
| cost / 帳單 / 月費 / drift / 升降 bundle / 預算 | 觸發 `billing` skill;baseline 數字看 `docs/reference/cost_baseline.md` **(SoT)**;盤點 SOP 看 `docs/sop/cost_review.md` |
| 502 / Caddy / SSL / DB 直查 / pipeline 鎖 / 用戶資料 | `docs/sop/debug.md` |
| 部署流程 / env / migration / Sentry env | `docs/sop/deploy.md` |
| backend 測試 / uv / provider registry / 任務派遣 | `docs/sop/backend.md` |
| iOS 編譯 SOP / 模組速查 / Sentry iOS | `docs/sop/ios.md` |
| 上架 App Store / 改文案 metadata / 查審查狀態 / 被拒處理 | `docs/sop/ios.md §發版` + `ops/asc.sh`(查詢/改文案)、`ops/ios_release.sh`(出 build) |
| 版號發版 / bump / tag / changelog / 發布上生產(api、ios) | `ops/release.sh`(`status`/`changelog`/`bump`/`tag`(原 `publish`,推 origin main=標記非部署)/`release <backend\|ios>`(三平面統一發布,唯一碰生產),單一入口);三平面語意見 `docs/sop/release.md`;`/release` command 為薄路由 |
| UI 規範 / Motion 契約 / Token 禁令 | `docs/sop/ui-design.md` |
| iOS↔backend sync / 多帳戶隔離 / 架構脈絡 | `docs/sop/architecture.md` |
| Claude Code Gateway | `docs/sop/claude-gateway.md` |
| host / port / container 配置(Caddy 路由) | `docs/reference/host_topology.md` **(SoT)** |
| 生產禁用指令 / preflight / rollback | `docs/policy/safety.md` **(SoT)** — 已寫進鐵律 7 |
| ops 流程 / change flow / hard stop | `docs/runbook/system.md` |
| 逐項 review 落地(派 review agent / PASS 判準 / block 處理) | `docs/sop/review_discipline.md` — 鐵律 4 落地 |
| 找 iOS UI 死碼 / 孤兒元件(刪元件 / cleanup / 重構前盤點) | `./ops/ui_deadcode.py`(IndexStore-based;default struct,class 可信 gate)— 見 `docs/reference/tech_index.md` |
| 查 iOS UI 元件依賴 / 改某 view 的 impact / 哪個 catalog surface 吃到它 | `./ops/ui_graph.py --type <Name>` 或 `./ops/ui_graph.py --surface <Catalog Surface>`(type→type 依賴圖;`--json`/`--dot`)— 見 `docs/reference/tech_index.md` |
| 查 UI 品質機制全景 / 我改的檔該跑哪些 UI gate | 優先 `./ops/ios_ops.sh quality list --json` / `quality impact --files <paths...> --json`(委派 `ops/ui_quality_plane.py`;機器可讀 SoT `ops/ui_quality_plane.yml`:分層機制×entrypoint×gate×verdict)— 見 `docs/reference/tech_index.md` |

## Doc Tier 契約

每份 doc 的 frontmatter 都有 `tier`;活文檔的長期 ownership / trigger / source hint 另以 `docs/registry.yml` 為機器可讀 SoT(`sources` 內 `!path` / `!glob` 表示排除 broad source 下的已知誤報)。改實作前先確認 registry 與 tier:

- **contract / reference / policy** — 活契約或索引。改相關語意 surface 必**同 PR** 更新對應 doc(routers / DB / env / iOS feature scope / CSV schema / host topology / safety),並把 `verified_against` 指到 main 可達 code commit。標 **(SoT)** 者衝突時權威。
- **sop**(`docs/sop/*`) — SOP 流程變了才更新;不是 code-as-doc。
- **generated** — registry 必須宣告 `generator` **與 `check`**(等值檢查命令,產物 != generator 輸出就 exit 1);產物不手改。缺 `check` 是 `docs_lint.sh --registry` 的 ERROR——`generator` 只宣告「這是產物」,`check` 才讓那個宣告可被機器驗證。
- **snapshot**(`docs/snapshot/*`) — 機器生成或 dated。讀前看 `verified_against`,**可能已過時**。
- **policy**(`docs/policy/*`) — 動之前需明確決策,PR 必須說明改動原因。
- **archive**(`docs/archive/*`) — 凍結歷史 strategy/audit,**不更新、不引用**。需要當前狀態請讀對應 sop / reference。
- **runbook**(`docs/runbook/*`) — ops change flow / hard stop;由 `devops` skill 引用。
- **assets**(`docs/assets/*`) — App Store / 行銷素材製作 SOP(promo video / screenshot framing)。不在 `ops/docs_lint.sh` staleness 掃描範圍,但仍須有 `<!-- doc-meta -->` frontmatter。
- **legal**(`docs/legal/*`) — 對外發布的隱私政策 / EULA。**不**強制 `<!-- doc-meta -->` frontmatter,亦不在 lint 掃描範圍;改動需走法務審閱,不適用 doc-as-code 規則。

## Doc Freshness 自動同步

> **執行方式(預設)**:doc 同步**派 background doc-sync agent**,不佔主線。code task commit 後,`Agent(subagent_type: general-purpose, model: opus, run_in_background: true)` + 極短 prompt:「讀 `docs/sop/doc_sync.md` 與 `docs/registry.yml`,必要時跑 `ops/docs_impact.py --since <base>`。依 registry trigger 同步 git commit `<hash>` 的文檔並 commit。改動摘要:<一兩句>」。agent 自讀 registry、用 impact hints 輔助判斷影響範圍、bump verified_against 到 main 可達 code commit、跑 docs gate、自行 `docs:` commit。主線不阻塞。純樣板(typo/rename)或 doc-only commit 不必派。

- 修改 backend router / DB schema / env var / ops 腳本 → 同 PR 更新 `docs/reference/tech_index.md`
- 新增 user-facing feature(iOS / backend / admin / chrome) → 同 PR 在 `docs/reference/product_surface.md` 追加 bullet
- iOS feature 重構(改檔名/分層/移檔) → 同 PR 更新對應 `docs/reference/feature_boundary/*.md`
- sync 邏輯 / CSV schema / host topology / safety 規則變動 → 同 PR 更新對應 (SoT) doc
- `backend/src/kg/llm/providers.py:REGISTRY` 費率變動 / Lightsail bundle 變更 / 新供應商接入 → 同 PR 更新 `docs/reference/cost_baseline.md`(對應段 §2 pricing / §1 月費表 / §5 變更歷史)
- iOS 大規模重構**落地後**執行 `ops/gen_ios_baseline.sh --write` 再生 `docs/snapshot/ios_baseline.md`(script 產出,不手改;預設是印 stdout,`--write` 才落檔)
- **cutover 前**跑 `ops/docs_lint.sh` 確認 registry + 本次 changed docs 無 ERROR,並檢視 registry impact hints 是否需要同步文件;全 repo 健康盤點另用 `ops/docs_lint.sh --audit`/`--all`,不把既有 audit debt 當日常 gate
