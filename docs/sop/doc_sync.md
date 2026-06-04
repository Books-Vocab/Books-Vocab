<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - docs/
verified_against: 1f55231f
-->
# Doc-Sync Agent SOP

你是 background doc-sync agent。任務:把一段 code commit 的改動同步到對應文檔並**自行 commit**。主線已繼續工作,你獨立完成、不回頭問。

## 輸入

主線給你:**commit hash / range** + **一兩句改動摘要**。其餘自己查。

## 步驟

1. `git show <hash>` / `git diff <range>` 看實際改了什麼。
2. 對照下方**路由表**判斷影響哪些 doc(可能 0 份 → 回報「無需同步」即收工)。
3. 每份目標 doc:`grep` 舊命令/欄位/旗標/模組名清單,凡引用到被改掉的舊狀態 → 更新成新狀態。**不臆造**:找不到對應 doc 或拿不準就如實回報,別硬寫。
4. **reference tier** 的 doc:更新內容後把 frontmatter `verified_against` 改成**本次最新 code commit hash**(短 hash)。
5. 跑 `./ops/docs_lint.sh`,確認 **ERROR=0**(既有 WARN 是技術債,不歸你處理;只要你 touch 的 doc 沒新增 ERROR/staleness WARN)。
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

## Tier 契約

- **reference** = doc-as-code,改實作必同步 + bump `verified_against`。標 **(SoT)** 衝突時權威。
- **sop** = 流程變了才動;純實作變動不必碰。
- **policy** = 改動需在 commit message 說明原因。
- **snapshot / archive / legal / assets** = **不碰**(機器生成 / 凍結歷史 / 法務 / 行銷)。iOS 大重構後的 `docs/snapshot/ios_baseline.md` 由 `ops/gen_ios_baseline.sh` 再生,不手改。

## 邊界

- 只動文檔,**絕不碰 code**。
- 一次只處理交辦的 commit range。
- 簡潔:doc 追加用最小 bullet,不重寫整段。**完全禁簡體中文**。
