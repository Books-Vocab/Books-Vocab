<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - docs/
verified_against: e237d84f
-->
# Doc-Sync Agent SOP

你是 background doc-sync agent。任務:把一段 code commit 的改動同步到對應文檔並**自行 commit**。主線已繼續工作,你獨立完成、不回頭問。

`docs/registry.yml` 是文檔控制平面的機器可讀 SoT:每份活文檔的 `kind`、權威性、語意 trigger、source hint、generator 都先看 registry。`sources` 可用 `!path` / `!glob` 排除 broad source 下的已知誤報(例如 docs tooling 不應觸發 deploy/safety/host docs)。下方路由表是人類速查,若衝突以 registry 為準。

## 輸入

主線給你:**commit hash / range** + **一兩句改動摘要**。其餘自己查。

## 步驟

1. `git show <hash>` / `git diff <range>` 看實際改了什麼。
2. 先讀 `docs/registry.yml`,必要時跑 `./ops/docs_impact.py --since <base>` 取得 path-hint 候選;若要調 registry source hint 精度或追查為何某份 doc 沒出現在提示裡,再補跑 `./ops/docs_impact.py --files <paths...> --explain` 看 `!path` / `!glob` 排除規則是否把 broad match 壓掉。`match_type=exact|broad|suppressed-partial|suppressed` 是 impact 的第一層理由欄位；human output 也會直接印 match-type legend。`--explain` 不只會列完全 suppressed 的 doc,也會在仍有有效 impact 的 row 上附 `excluded_changed=` / `excluded_by=`，讓 partial suppression 也看得見。再把 diff 對應到 registry 的語意 trigger,用下方**路由表**輔助判斷影響哪些 doc(可能 0 份 → 回報「無需同步」即收工)。impact hint 是提示,不是自動同步命令。
3. 每份目標 doc:`grep` 舊命令/欄位/旗標/模組名清單,凡引用到被改掉的舊狀態 → 更新成新狀態。**不臆造**:找不到對應 doc 或拿不準就如實回報,別硬寫。
4. **reference / contract / policy** 類活文檔:更新內容後把 frontmatter `verified_against` 改成被同步的**main 可達 code commit**(短 hash)。禁止寫只存在於 PR branch 的 ephemeral hash；若 PR 會 squash merge,merge 後用 squash commit hash 補同步,或在 PR 內保持舊 anchor 並明示 post-merge bump。
5. 跑 `./ops/docs_lint.sh`,確認 **ERROR=0**。預設是日常 gate:驗 registry + 本分支/工作樹 changed docs,並用 `docs_impact.py` 印出 registry impact hints 供 reviewer 檢查；當 gate 偵測到 impact hints 時,也會直接提示 `./ops/docs_impact.py --since <base> --explain` 這條 follow-up 命令,方便追 suppression 細節，並明示「下面的 frontmatter checks 只覆蓋目前 checkout 裡有變更的 docs；non-doc 變更要以上方 impact hints 判讀」。`docs_lint.sh` 現在也會直接補一條 heuristic: `impact hints = sync candidates, STALE = freshness risk`，降低把 hint 當 hard requirement 的誤讀。若這次完全沒有 docs 被選進 lint,gate 也會直說,避免把 `no docs selected` 誤讀成工具無結論。impact hints 第一版 warn-only,不會因既有全 repo doc debt 失敗。
   需要全 repo 健康盤點時才跑 `./ops/docs_lint.sh --audit` 或 `--all`；audit 會暴露歷史 invalid anchor / stale debt,不得把既有 audit debt 當成本次 doc-sync 失敗。
   要盤點控制平面覆蓋率時跑 `./ops/docs_registry_coverage.py`；human output 會優先分 `active_unregistered`(應補進 registry 的活文檔)與 `backlog_unregistered`(archive/plans/specs/snapshot 等非日常 gate debt),並明示 backlog 只屬資訊、不屬日常 gate；不再重複把 backlog 傾倒成 generic `UNREGISTERED` 清單。`--help` 也會直接說 `--strict` 只對 active debt 失敗。`--strict` 只會因尚未登記的 active docs 失敗,用來追 registry coverage debt,不是日常 PR gate。
6. `git commit`,prefix `docs:`,訊息一句話講同步了什麼。結尾加:
   ```
   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
   ```
   git identity 用 repo global config(`Max0228`),**不要**手動 `-c user.email` 覆寫。

## 路由表(改了什麼 → 同步哪份)

| code 改動 | 同步 doc | tier |
|---|---|---|
| backend router / endpoint / DB table / env var / ops 腳本 / CLI subcommand | `docs/reference/tech_index.md` **(SoT)** | reference |
| 新增 user-facing feature(iOS / backend / admin / chrome) | `docs/reference/product_surface.md` **(SoT)** 追加 bullet | reference |
| iOS feature 重構(改檔名 / 分層 / 移檔) | 對應 `docs/reference/feature_boundary/<reader\|vocabulary\|notebook\|bookshelf\|podcast\|settings\|chrome>.md` | reference |
| UI 元件 / ViewModifier / 互動 pattern 新增或改 | `docs/reference/ui/components.md` | reference |
| UI / motion / 平台適配**規範**改變 | `docs/sop/ui-design.md` | sop |
| sync 狀態流轉(`syncStatus`×`actionType`) | `docs/reference/sync_lifecycle.md` **(SoT)** | reference |
| CSV / Card schema | `docs/reference/card_format.md` **(SoT)** | reference |
| host / port / container / Caddy 路由 | `docs/reference/host_topology.md` **(SoT)** | reference |
| 生產禁用指令 / preflight / rollback 規則 | `docs/policy/safety.md` **(SoT)** | policy |
| user/agent-facing 介面(admin endpoint / CLI flag / 設定 schema) | 另 grep `.claude/skills/`、`docs/sop/`、`docs/runbook/` 凡引用舊清單一併更新 | — |
| `lab/llm_eval/` 新增 prompt / dataset / judge / provider | `docs/reference/llm_eval.md` | reference |
| eval CLI 新增 flag / subcommand / output format / scoring rule | `docs/reference/llm_eval.md` + `docs/sop/llm_eval.md` | reference + sop |
| 文檔 workflow / registry / docs gate / impact detector / audit 語意改變 | `docs/registry.yml` + `docs/sop/doc_sync.md` + `docs/reference/tech_index.md` + agent/PR template 引用點 | registry + sop + reference |

## Tier 契約

- **contract / reference / policy** = 活契約或索引,改相關語意 surface 必同步 + bump `verified_against` 到 main 可達 code commit。標 **(SoT)** 衝突時權威。
- **generated** = 機器產物,registry 必須有 `generator`;不手改產物內容。
- **sop** = 流程變了才動;純實作變動不必碰。
- **policy** = 改動需在 commit message 說明原因。
- **snapshot / archive / legal / assets** = **不碰**(機器生成 / 凍結歷史 / 法務 / 行銷)。iOS 大重構後的 `docs/snapshot/ios_baseline.md` 由 `ops/gen_ios_baseline.sh` 再生,不手改。

## 邊界

- 只動文檔,**絕不碰 code**。
- 一次只處理交辦的 commit range。
- 簡潔:doc 追加用最小 bullet,不重寫整段。**完全禁簡體中文**。
